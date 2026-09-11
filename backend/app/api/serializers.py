"""ORM model -> response schema conversion.

Kept out of the route modules so a shape like "a user card" or "a clip" is
defined once and reused everywhere it's embedded (feed, comments, team
members), rather than reimplemented per route. These are the only place
`app.services.storage` is touched for URL-building outside the routes.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clip import Clip
from app.models.social import Comment, Follow, Like
from app.models.user import User
from app.schemas.clip import AnalysisOut, ClipOut, TrickOut
from app.schemas.social import CommentOut
from app.schemas.user import ProfileOut, UserBrief, UserPublic
from app.services.storage import get_storage


def _avatar_url(user: User) -> str | None:
    return get_storage().public_url(user.avatar_key) if user.avatar_key else None


def user_brief(user: User) -> UserBrief:
    return UserBrief(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=_avatar_url(user),
    )


async def user_public(user: User, db: AsyncSession, viewer: User | None = None) -> UserPublic:
    follower_count = await db.scalar(
        select(func.count()).select_from(Follow).where(Follow.followee_user_id == user.id)
    )
    following_count = await db.scalar(
        select(func.count()).select_from(Follow).where(Follow.follower_id == user.id)
    )

    followed_by_me = False
    if viewer is not None and viewer.id != user.id:
        followed_by_me = (
            await db.scalar(
                select(Follow.id).where(
                    Follow.follower_id == viewer.id, Follow.followee_user_id == user.id
                )
            )
        ) is not None

    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=_avatar_url(user),
        profile=ProfileOut.model_validate(user.profile) if user.profile else None,
        follower_count=follower_count or 0,
        following_count=following_count or 0,
        followed_by_me=followed_by_me,
        created_at=user.created_at,
    )


async def clip_out(
    clip: Clip,
    db: AsyncSession,
    viewer: User | None = None,
    *,
    like_count: int | None = None,
    comment_count: int | None = None,
    liked_by_me: bool | None = None,
) -> ClipOut:
    """Requires clip.user / clip.analyses / clip.clip_tricks to be loaded —
    they're all lazy="selectin" on the model, so any query that fetches the
    Clip populates them.

    The three engagement values default to a per-clip query each (mirroring
    user_public's per-call count queries), but a caller looping over many
    clips — feed.py, up to 50 per page — can precompute all three with one
    batched clip_engagement() call below and pass them in here instead of
    paying 2-3 queries per clip.
    """
    latest = clip.analyses[0] if clip.analyses else None
    if like_count is None:
        like_count = (
            await db.scalar(select(func.count()).select_from(Like).where(Like.clip_id == clip.id))
            or 0
        )
    if comment_count is None:
        comment_count = (
            await db.scalar(
                select(func.count()).select_from(Comment).where(Comment.clip_id == clip.id)
            )
            or 0
        )
    if liked_by_me is None:
        liked_by_me = (
            viewer is not None
            and (
                await db.scalar(
                    select(Like.clip_id).where(Like.clip_id == clip.id, Like.user_id == viewer.id)
                )
            )
            is not None
        )
    return ClipOut(
        id=clip.id,
        status=clip.status,
        author=user_brief(clip.user),
        video_url=await get_storage().presign_download(clip.s3_key),
        duration_ms=clip.duration_ms,
        source_fps=clip.source_fps,
        steeze_score=clip.steeze_score,
        published_at=clip.published_at,
        tricks=[TrickOut.model_validate(ct.trick) for ct in clip.clip_tricks],
        analysis=AnalysisOut.model_validate(latest) if latest else None,
        like_count=like_count,
        comment_count=comment_count,
        liked_by_me=liked_by_me,
        created_at=clip.created_at,
    )


async def clip_engagement(
    clip_ids: Sequence[uuid.UUID], db: AsyncSession, viewer: User | None
) -> dict[uuid.UUID, dict[str, int | bool]]:
    """Batches the like/comment counts and the viewer's like state for a
    whole page of clips — one grouped query per metric instead of clip_out's
    default per-clip queries. Used by feed.py; single-clip routes in
    routes/clips.py let clip_out query directly instead."""
    if not clip_ids:  # empty feed page — skip three queries, and .in_(()) warns
        return {}
    likes = dict(
        (
            await db.execute(
                select(Like.clip_id, func.count())
                .where(Like.clip_id.in_(clip_ids))
                .group_by(Like.clip_id)
            )
        ).all()
    )
    comments = dict(
        (
            await db.execute(
                select(Comment.clip_id, func.count())
                .where(Comment.clip_id.in_(clip_ids))
                .group_by(Comment.clip_id)
            )
        ).all()
    )
    liked_by_me: set[uuid.UUID] = set()
    if viewer is not None:
        liked_by_me = set(
            await db.scalars(
                select(Like.clip_id).where(Like.clip_id.in_(clip_ids), Like.user_id == viewer.id)
            )
        )
    return {
        cid: {
            "like_count": likes.get(cid, 0),
            "comment_count": comments.get(cid, 0),
            "liked_by_me": cid in liked_by_me,
        }
        for cid in clip_ids
    }


def comment_out(comment: Comment) -> CommentOut:
    """No db param needed — comment.author (lazy="selectin", applies
    automatically) and comment.replies are both expected to already be
    loaded. replies is self-referential, so its own lazy="raise_on_sql"
    never auto-applies; the caller's query must eager-load it explicitly
    via .options(selectinload(Comment.replies)) — see routes/clips.py — or
    this raises rather than silently emitting SQL."""
    return CommentOut(
        id=comment.id,
        clip_id=comment.clip_id,
        author=user_brief(comment.author),
        body=comment.body,
        parent_id=comment.parent_id,
        # A reply can't have replies (enforced in routes/clips.py), so this
        # only ever recurses one level deep.
        replies=[comment_out(r) for r in comment.replies] if comment.parent_id is None else [],
        created_at=comment.created_at,
    )
