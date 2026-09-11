"""Home feed — published clips from everyone you follow, newest first.

Fan-out-on-read (docs/ARCHITECTURE.md §7): a live join of `follows` against
`clips`, keyset-paginated. Cheap enough at this scale that precomputed
per-user timelines aren't worth their write amplification.
"""

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import and_, or_, select

from app.api.deps import CurrentUser, DbSession
from app.api.pagination import decode_cursor, encode_cursor
from app.api.serializers import clip_engagement, clip_out
from app.models.clip import Clip
from app.models.enums import ClipStatus
from app.models.social import Follow
from app.schemas.clip import FeedPage

router = APIRouter(prefix="/feed", tags=["feed"])

_PAGE_MAX = 50


@router.get("")
async def home_feed(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=_PAGE_MAX),
    cursor: str | None = None,
) -> FeedPage:
    stmt = (
        select(Clip)
        .join(Follow, Follow.followee_user_id == Clip.user_id)
        .where(Follow.follower_id == user.id)
        .where(Clip.status == ClipStatus.PUBLISHED)
        .order_by(Clip.published_at.desc(), Clip.id.desc())
        .limit(limit + 1)  # one extra row tells us whether there's a next page
    )

    try:
        keyset = decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "malformed cursor") from exc

    if keyset is not None:
        # The (published_at, id) < (?, ?) keyset from ARCHITECTURE §7, spelled
        # out as an OR rather than a row-value comparison — same result, and
        # each side is `column < scalar` so the bind-param types are never in
        # doubt (asyncpg is strict about that).
        cur_ts, cur_id = keyset
        stmt = stmt.where(
            or_(
                Clip.published_at < cur_ts,
                and_(Clip.published_at == cur_ts, Clip.id < cur_id),
            )
        )

    clips = list(await db.scalars(stmt))
    has_more = len(clips) > limit
    clips = clips[:limit]

    next_cursor = None
    if has_more and clips:
        last = clips[-1]
        next_cursor = encode_cursor(last.published_at, last.id)

    # One batched query per engagement metric for the whole page, instead of
    # clip_out's default per-clip queries — see clip_engagement's docstring.
    engagement = await clip_engagement([c.id for c in clips], db, user)
    items = [await clip_out(c, db, user, **engagement[c.id]) for c in clips]
    return FeedPage(items=items, next_cursor=next_cursor)
