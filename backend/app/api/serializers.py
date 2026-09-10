"""ORM model -> response schema conversion.

Kept out of the route modules so a shape like "a user card" or "a clip" is
defined once and reused everywhere it's embedded (feed, comments, team
members), rather than reimplemented per route. These are the only place
`app.services.storage` is touched for URL-building outside the routes.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clip import Clip
from app.models.social import Follow
from app.models.user import User
from app.schemas.clip import AnalysisOut, ClipOut, TrickOut
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


async def clip_out(clip: Clip) -> ClipOut:
    """Requires clip.user / clip.analyses / clip.clip_tricks to be loaded —
    they're all lazy="selectin" on the model, so any query that fetches the
    Clip populates them."""
    latest = clip.analyses[0] if clip.analyses else None
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
        created_at=clip.created_at,
    )
