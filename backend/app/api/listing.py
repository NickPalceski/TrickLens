"""One keyset-paginated page of clips, shared by every clip list: the home
feed, a user's clips, a team's clips, and your drafts. See
docs/components/api.md, Feed and Discover, for why keyset rather than OFFSET.
"""

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.api.pagination import decode_cursor, encode_cursor
from app.api.serializers import clip_engagement, clip_out
from app.models.clip import Clip
from app.models.user import User
from app.schemas.clip import FeedPage

PAGE_MAX = 50


async def clip_page(
    stmt: Select[tuple[Clip]],
    order_by: InstrumentedAttribute,
    db: AsyncSession,
    viewer: User | None,
    limit: int,
    cursor: str | None,
) -> FeedPage:
    """`stmt` selects and filters the clips; this orders them newest first
    by `order_by` (`Clip.published_at` or `Clip.created_at`, never null in
    the rows `stmt` picks) with `Clip.id` as the tie-break, and pages."""
    stmt = stmt.order_by(order_by.desc(), Clip.id.desc()).limit(limit + 1)

    try:
        keyset = decode_cursor(cursor)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "malformed cursor") from exc

    if keyset is not None:
        # The (ts, id) < (?, ?) keyset, spelled out as an OR rather than a
        # row-value comparison: same result, and each side is `column <
        # scalar`, so the bind-param types are never in doubt (asyncpg is
        # strict about that).
        cur_ts, cur_id = keyset
        stmt = stmt.where(or_(order_by < cur_ts, and_(order_by == cur_ts, Clip.id < cur_id)))

    clips = list(await db.scalars(stmt))
    has_more = len(clips) > limit  # the one extra row
    clips = clips[:limit]

    next_cursor = None
    if has_more and clips:
        last = clips[-1]
        next_cursor = encode_cursor(getattr(last, order_by.key), last.id)

    # One batched query per engagement metric for the whole page, instead of
    # clip_out's default per-clip queries — see clip_engagement's docstring.
    engagement = await clip_engagement([c.id for c in clips], db, viewer)
    items = [await clip_out(c, db, viewer, **engagement[c.id]) for c in clips]
    return FeedPage(items=items, next_cursor=next_cursor)
