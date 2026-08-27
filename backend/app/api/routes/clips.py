"""Clip upload -> analyze -> tag -> publish endpoints.

Cognito owns identity (see routes/users.py); this module owns the clip
lifecycle described in docs/ARCHITECTURE.md §3. The browser uploads straight
to S3 — the API only ever hands out presigned URLs and moves the row through
ClipStatus. The worker (app/worker.py) does the actual analyzing.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbSession
from app.models.clip import Clip, ClipTrick, Trick
from app.models.enums import ClipStatus
from app.schemas.clip import (
    AnalysisOut,
    ClipCreate,
    ClipCreateOut,
    ClipOut,
    TagTricksRequest,
    TrickOut,
)
from app.services.queue import get_queue
from app.services.storage import PREFIX_RAW, get_storage

router = APIRouter(prefix="/clips", tags=["clips"])

# Extensions the presigned key is built with. Anything else is rejected at
# creation rather than discovered later when the worker can't make sense of
# the object.
_EXTENSIONS = {
    "video/mp4": "mp4",
    "video/quicktime": "mov",
    "video/webm": "webm",
}


async def _to_out(clip: Clip) -> ClipOut:
    latest = clip.analyses[0] if clip.analyses else None
    return ClipOut(
        id=clip.id,
        status=clip.status,
        video_url=await get_storage().presign_download(clip.s3_key),
        duration_ms=clip.duration_ms,
        source_fps=clip.source_fps,
        steeze_score=clip.steeze_score,
        published_at=clip.published_at,
        tricks=[TrickOut.model_validate(ct.trick) for ct in clip.clip_tricks],
        analysis=AnalysisOut.model_validate(latest) if latest else None,
        created_at=clip.created_at,
    )


async def _get_owned(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Clip:
    """Fetch a clip the caller owns, or 404 — same privacy reasoning as
    step 2's user lookups: don't confirm someone else's draft exists."""
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    if clip is None or clip.user_id != user.id:
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
    # relationships _to_out reads are populated consistently — same reason
    # as the equivalent re-fetch in routes/users.py's register().
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    return ClipCreateOut(clip=await _to_out(clip), upload_url=presigned["url"])


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
    return await _to_out(clip)


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
    return await _to_out(clip)


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
    return await _to_out(clip)


@router.get("/{clip_id}")
async def read_clip(clip_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ClipOut:
    """Owner-only pre-publish; visible to any authenticated user once
    published. There's no public/unauthenticated route yet — nothing links
    to clips outside their owner until the feed exists (step 4)."""
    clip = await db.scalar(select(Clip).where(Clip.id == clip_id))
    if clip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    if clip.status != ClipStatus.PUBLISHED and clip.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "clip not found")
    return await _to_out(clip)
