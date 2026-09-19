"""Steeze score aggregation.

Shared between live API responses (api/serializers.py's user_public/team_out)
and the Discover rankings job (app/rankings.py) — both need the *exact* same
definition, or a team's live-displayed average and the historical snapshot
used to compute its Discover ranking delta would silently drift apart.
"""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.clip import Clip
from app.models.enums import ClipStatus

# Team score = average of the team's top 10 clips, not all of them —
# otherwise the biggest roster always wins and a score could never fall
# (docs/ARCHITECTURE.md §6/§10). A user's own average has no analogous
# fairness problem, so it stays uncapped.
TEAM_SCORE_TOP_N = 10


async def user_average_score(db: AsyncSession, user_id: uuid.UUID) -> Decimal | None:
    """Uncapped average across every published, score-included clip. None
    if the user has none — distinct from a real 0, which would read as a
    terrible score rather than "no rated clips yet"."""
    return await db.scalar(
        select(func.avg(Clip.steeze_score)).where(
            Clip.user_id == user_id,
            Clip.status == ClipStatus.PUBLISHED,
            Clip.score_included.is_(True),
        )
    )


async def team_average_score(db: AsyncSession, team_id: uuid.UUID) -> Decimal | None:
    """Average of the team's top 10 published, score-included clips by
    steeze_score. None if it has none."""
    top = (
        select(Clip.steeze_score)
        .where(
            Clip.team_id == team_id,
            Clip.status == ClipStatus.PUBLISHED,
            Clip.score_included.is_(True),
        )
        .order_by(Clip.steeze_score.desc())
        .limit(TEAM_SCORE_TOP_N)
        .subquery()
    )
    return await db.scalar(select(func.avg(top.c.steeze_score)))
