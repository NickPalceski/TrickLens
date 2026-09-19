"""Clip upload -> analyze -> tag -> publish endpoints.

Cognito owns identity (see routes/users.py); this module owns the clip
lifecycle described in docs/ARCHITECTURE.md §3. The browser uploads straight
to S3 — the API only ever hands out presigned URLs and moves the row through
ClipStatus. The worker (app/worker.py) does the actual analyzing.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import decode_cursor, encode_cursor
from app.api.serializers import clip_out, comment_out
from app.models.clip import Clip, ClipTrick, Trick
from app.models.enums import ClipStatus
from app.models.social import Comment, Like
from app.models.team import Team, TeamMember
from app.models.user import User
from app.schemas.clip import (
    ClipCreate,
    ClipCreateOut,
    ClipOut,
    ClipScoreInclusionUpdate,
    ClipTeamUpdate,
    TagTricksRequest,
)
from app.schemas.social import CommentCreate, CommentOut, CommentPage
from app.services.queue import get_queue
from app.services.storage import PREFIX_RAW, get_storage

router = APIRouter(prefix="/clips", tags=["clips"])
_PAGE_MAX = 50

# Extensions the presigned key is built with. Anything else is rejected at
# creation rather than discovered later when the worker can't make sense of
# the object.
_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


async def _get_owned(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Clip:
    """Fetch a clip the caller owns, or 404 — same privacy reasoning as
    step 2's user lookups: don't confirm someone else's draft exists."""
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    if clip is None or clip.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    return clip


async def _get_visible(clip_id: uuid.UUID, user: User, db: DbSession) -> Clip:
    """A clip the caller may see: published, or their own (any status) —
    same privacy rule read_clip has always enforced, factored out so the
    like/comment routes below share it. 404, not 403: a stranger shouldn't
    be able to tell a private draft exists."""
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    if clip is None or (clip.status != ClipStatus.PUBLISHED and clip.user_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    return clip


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_clip(body: ClipCreate, user: CurrentUser, db: DbSession) -> ClipCreateOut:
    ext = _EXTENSIONS.get(body.content_type)
    if ext is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported content type")

    clip_id = uuid.uuid4()
    clip = Clip(
        id=clip_id,
        user_id=user.id,
        s3_key=f"{PREFIX_RAW}/{clip_id}.{ext}",
        duration_ms=body.duration_ms,
        source_fps=body.source_fps,
    )
    db.add(clip)
    await db.flush()

    presigned = await get_storage().presign_upload(clip.s3_key, body.content_type)

    # Re-fetch through a query so server-generated columns and the
    # relationships clip_out reads are populated consistently — same reason
    # as the equivalent re-fetch in routes/users.py's register().
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    return ClipCreateOut(clip=await clip_out(clip, db, user), upload_url=presigned["url"])


@router.post("/{clip_id}/complete")
async def complete_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    clip = await _get_owned(clip_id, user, db)
    if clip.status != ClipStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, f"clip is already {clip.status}")

    if await get_storage().head(clip.s3_key) is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "upload not found — PUT to the presigned URL first",
        )

    clip.status = ClipStatus.QUEUED
    # Commit before enqueueing, not after: LocalStack/SQS can deliver a
    # message fast enough that the worker reads the clip row before this
    # transaction would otherwise have committed, seeing stale status=draft.
    await db.commit()

    await get_queue().enqueue({"clip_id": str(clip.id), "s3_key": clip.s3_key})
    return await clip_out(clip, db, user)


@router.post("/{clip_id}/tricks")
async def tag_tricks(
    clip_id: uuid.UUID, body: TagTricksRequest, user: CurrentUser, db: DbSession
) -> ClipOut:
    clip = await _get_owned(clip_id, user, db)
    if clip.status != ClipStatus.ANALYZED:
        raise HTTPException(status.HTTP_409_CONFLICT, "clip must be analyzed before tagging")

    await db.execute(delete(ClipTrick).where(ClipTrick.clip_id == clip.id))

    for position, name in enumerate(body.tricks):
        canonical_name = name.lower()
        trick = await db.scalar(select(Trick).where(Trick.canonical_name == canonical_name))
        if trick is None:
            trick = Trick(canonical_name=canonical_name)
            db.add(trick)
            await db.flush()
        db.add(ClipTrick(clip_id=clip.id, trick_id=trick.id, position=position))

    await db.flush()
    # clip.clip_tricks was already loaded (stale) by _get_owned's initial
    # query, earlier in this same session — the delete+insert above doesn't
    # invalidate that in-memory collection on its own, so it needs an
    # explicit refresh rather than a re-SELECT (which would just return the
    # same identity-mapped, still-stale object).
    await db.refresh(clip, attribute_names=["clip_tricks"])
    return await clip_out(clip, db, user)


@router.patch("/{clip_id}/team")
async def set_clip_team(
    clip_id: uuid.UUID, body: ClipTeamUpdate, user: CurrentUser, db: DbSession
) -> ClipOut:
    """One-time, pre-publish decision (4c) — `team_id: null` clears it.
    Locked once published, unlike score-inclusion below: a team tag is
    credit for a specific team roster at a point in time, not something that
    makes sense to reassign after the fact."""
    clip = await _get_owned(clip_id, user, db)
    if clip.status != ClipStatus.ANALYZED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "clip must be analyzed, and not yet published, to tag a team"
        )

    team = None
    if body.team_id is not None:
        membership = await db.scalar(
            select(TeamMember).where(
                TeamMember.team_id == body.team_id, TeamMember.user_id == user.id
            )
        )
        if membership is None:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "you must be a member of the team to tag a clip to it"
            )
        team = await db.scalar(select(Team).where(Team.id == body.team_id))

    # Assigning through the relationship (not clip.team_id directly) keeps
    # the in-memory clip.team attribute in sync — clip_out reads it right
    # below with no re-fetch, unlike tag_tricks' clip_tricks collection,
    # which needs an explicit refresh after a bulk delete+insert.
    clip.team = team
    await db.flush()
    return await clip_out(clip, db, user)


@router.patch("/{clip_id}/score-inclusion")
async def set_score_inclusion(
    clip_id: uuid.UUID, body: ClipScoreInclusionUpdate, user: CurrentUser, db: DbSession
) -> ClipOut:
    """Unlike team tagging, this stays editable forever, even after
    publishing — an edit to the post, not a one-time pre-publish call. Never
    touches Analysis; the existing scoring pass is reused as-is either way,
    see app/models/clip.py."""
    clip = await _get_owned(clip_id, user, db)
    if clip.status not in (ClipStatus.ANALYZED, ClipStatus.PUBLISHED):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "clip must be analyzed before its score can be toggled"
        )
    clip.score_included = body.included
    await db.flush()
    return await clip_out(clip, db, user)


@router.post("/{clip_id}/publish")
async def publish_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    clip = await _get_owned(clip_id, user, db)
    if clip.status != ClipStatus.ANALYZED:
        raise HTTPException(status.HTTP_409_CONFLICT, "clip must be analyzed before publishing")
    if not clip.clip_tricks:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "tag at least one trick before publishing"
        )

    clip.status = ClipStatus.PUBLISHED
    clip.published_at = datetime.now(UTC)
    await db.flush()
    return await clip_out(clip, db, user)


@router.get("/{clip_id}")
async def read_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    """Owner-only pre-publish; visible to any authenticated user once
    published. There's no public/unauthenticated route yet — nothing links
    to clips outside their owner until the feed exists (step 4)."""
    clip = await _get_visible(clip_id, user, db)
    return await clip_out(clip, db, user)


@router.post("/{clip_id}/like", status_code=status.HTTP_201_CREATED)
async def like_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    """No self-like restriction — unlike following yourself, which is
    structurally nonsensical, liking your own clip is normal and harmless."""
    clip = await _get_visible(clip_id, user, db)
    if clip.status != ClipStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "clip must be published to like")

    already = await db.scalar(
        select(Like.clip_id).where(Like.user_id == user.id, Like.clip_id == clip.id)
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already liked")

    db.add(Like(user_id=user.id, clip_id=clip.id))
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race against a concurrent like
        raise HTTPException(status.HTTP_409_CONFLICT, "already liked") from exc
    return await clip_out(clip, db, user)


@router.delete("/{clip_id}/like")
async def unlike_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    clip = await _get_visible(clip_id, user, db)
    # Idempotent: unliking a clip you haven't liked is a no-op 200.
    await db.execute(delete(Like).where(Like.user_id == user.id, Like.clip_id == clip.id))
    await db.flush()
    return await clip_out(clip, db, user)


@router.post("/{clip_id}/comments", status_code=status.HTTP_201_CREATED)
async def add_comment(
    clip_id: uuid.UUID, body: CommentCreate, user: CurrentUser, db: DbSession
) -> CommentOut:
    clip = await _get_visible(clip_id, user, db)
    if clip.status != ClipStatus.PUBLISHED:
        raise HTTPException(status.HTTP_409_CONFLICT, "clip must be published to comment")

    if body.parent_id is not None:
        parent = await db.scalar(
            select(Comment).where(Comment.id == body.parent_id, Comment.clip_id == clip.id)
        )
        if parent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "parent comment not found")
        if parent.parent_id is not None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "cannot reply to a reply")

    comment = Comment(clip_id=clip.id, user_id=user.id, body=body.body, parent_id=body.parent_id)
    db.add(comment)
    await db.flush()
    # Re-fetch so author (lazy="selectin", applies automatically) is
    # populated — same reason routes/users.py's register() re-fetches after
    # add()+flush(). replies needs an explicit selectinload(): SQLAlchemy
    # does not auto-apply a relationship's default lazy="selectin" strategy
    # for self-referential relationships (it would risk unbounded recursive
    # loading on tree-shaped data), so it must be requested per-query.
    comment = await db.scalar(
        select(Comment).where(Comment.id == comment.id).options(selectinload(Comment.replies))
    )
    return comment_out(comment)


@router.get("/{clip_id}/comments")
async def list_comments(
    clip_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=_PAGE_MAX),
    cursor: str | None = None,
) -> CommentPage:
    """Top-level comments only, newest first, keyset-paginated exactly like
    GET /feed. Each item's replies ride along via an explicit selectinload()
    — one extra query for the whole page, not one per comment. (Comment.replies
    is self-referential, so its mapper-level lazy="selectin" default never
    auto-applies — see the comment in add_comment above.)"""
    clip = await _get_visible(clip_id, user, db)

    stmt = (
        select(Comment)
        .where(Comment.clip_id == clip.id, Comment.parent_id.is_(None))
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .limit(limit + 1)
        .options(selectinload(Comment.replies))
    )

    try:
        keyset = decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "malformed cursor") from exc

    if keyset is not None:
        cur_ts, cur_id = keyset
        stmt = stmt.where(
            or_(
                Comment.created_at < cur_ts,
                and_(Comment.created_at == cur_ts, Comment.id < cur_id),
            )
        )

    comments = list(await db.scalars(stmt))
    has_more = len(comments) > limit
    comments = comments[:limit]

    next_cursor = None
    if has_more and comments:
        last = comments[-1]
        next_cursor = encode_cursor(last.created_at, last.id)

    return CommentPage(items=[comment_out(c) for c in comments], next_cursor=next_cursor)


@router.delete("/{clip_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    clip_id: uuid.UUID, comment_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> None:
    """Deletable by its author or the clip's owner (basic moderation) — not
    just the author, unlike everything else deleted so far in this API.
    204, not 200 + a body: unlike unfollow/unlike, which report the target's
    new state, a deleted-by-id comment has no "current state" left to
    report."""
    row = await db.execute(
        select(Comment, Clip.user_id)
        .join(Clip, Clip.id == Comment.clip_id)
        .where(Comment.id == comment_id, Comment.clip_id == clip_id)
    )
    result = row.first()
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "comment not found")
    comment, clip_owner_id = result

    if comment.user_id != user.id and clip_owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not allowed to delete this comment")

    # DB-level ondelete="CASCADE" on parent_id removes replies too.
    await db.execute(delete(Comment).where(Comment.id == comment.id))
    await db.flush()
