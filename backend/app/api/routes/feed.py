"""Home feed — published clips from everyone (and every team) you follow,
newest first.

Fan-out-on-read (docs/components/api.md, Feed and Discover): a live query against `clips`,
keyset-paginated. Cheap enough at this scale that precomputed per-user
timelines aren't worth their write amplification.
"""

from fastapi import APIRouter, Query
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.api.listing import PAGE_MAX, clip_page
from app.models.clip import Clip
from app.models.enums import ClipStatus
from app.models.social import Follow
from app.schemas.clip import FeedPage

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("")
async def home_feed(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> FeedPage:
    # Two IN-subqueries rather than a join on an OR condition: a join would
    # emit a clip twice when both its author *and* its tagged team are
    # followed, and de-duping a joined result is more awkward than just
    # avoiding the duplication in the first place.
    followed_users = select(Follow.followee_user_id).where(
        Follow.follower_id == user.id, Follow.followee_user_id.is_not(None)
    )
    followed_teams = select(Follow.followee_team_id).where(
        Follow.follower_id == user.id, Follow.followee_team_id.is_not(None)
    )
    stmt = (
        select(Clip)
        .where(or_(Clip.user_id.in_(followed_users), Clip.team_id.in_(followed_teams)))
        .where(Clip.status == ClipStatus.PUBLISHED)
    )
    return await clip_page(stmt, Clip.published_at, db, user, limit, cursor)
