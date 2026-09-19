"""Discover (4d): the week's top clips (by score or by engagement) and the
teams whose score is climbing fastest.

Both read from what app/rankings.py last wrote — `make rankings` locally,
an EventBridge-triggered Lambda in production (step 5) — never compute a
ranking live. See docs/ARCHITECTURE.md §7 for why.
"""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.serializers import clip_engagement, clip_out, team_brief
from app.models.clip import Clip
from app.models.discover import ClipRanking, TeamScoreHistory
from app.models.enums import ClipStatus
from app.models.team import Team
from app.rankings import WINDOW
from app.schemas.discover import DiscoverClipPage, DiscoverTeamPage, TeamRankingOut

router = APIRouter(prefix="/discover", tags=["discover"])
_PAGE_MAX = 50


@router.get("/clips")
async def top_clips(
    user: CurrentUser,
    db: DbSession,
    sort: Literal["score", "engagement"] = "score",
    limit: int = Query(20, ge=1, le=_PAGE_MAX),
    offset: int = Query(0, ge=0),
) -> DiscoverClipPage:
    """`sort=score` filters to score_included clips — if the owner said a
    clip's score isn't fair, it shouldn't rank on that score either, even
    though it stays fully visible everywhere else, engagement ranking
    included. `sort=engagement` has no such filter; it's a deliberately
    separate signal from the steeze score (app/rankings.py's
    ENGAGEMENT_WEIGHTS)."""
    order_col = ClipRanking.steeze_score if sort == "score" else ClipRanking.engagement_score
    stmt = (
        select(ClipRanking)
        .order_by(order_col.desc(), ClipRanking.clip_id)
        .offset(offset)
        .limit(limit + 1)
    )
    if sort == "score":
        stmt = stmt.where(ClipRanking.score_included.is_(True))

    rankings = list(await db.scalars(stmt))
    has_more = len(rankings) > limit
    rankings = rankings[:limit]
    ranked_ids = [r.clip_id for r in rankings]

    # Re-fetch the live Clip rows for display (current like/comment/view
    # counts, current status) — clip_rankings only decides *which* clips and
    # in *what order*, not what to show for them; see ClipRanking's
    # docstring. A clip deleted or unpublished since the last rebuild is
    # just dropped here rather than erroring, which can make a page come
    # back shorter than `limit` even when has_more is true — acceptable for
    # a snapshot that's only ever as fresh as the last rebuild.
    clips_by_id = {}
    if ranked_ids:
        rows = await db.scalars(
            select(Clip).where(Clip.id.in_(ranked_ids), Clip.status == ClipStatus.PUBLISHED)
        )
        clips_by_id = {c.id: c for c in rows}
    ordered_clips = [clips_by_id[cid] for cid in ranked_ids if cid in clips_by_id]

    engagement = await clip_engagement([c.id for c in ordered_clips], db, user)
    items = [await clip_out(c, db, user, **engagement[c.id]) for c in ordered_clips]

    next_offset = offset + limit if has_more else None
    return DiscoverClipPage(items=items, next_offset=next_offset)


@router.get("/teams")
async def top_teams(
    user: CurrentUser,
    db: DbSession,
    limit: int = Query(20, ge=1, le=_PAGE_MAX),
    offset: int = Query(0, ge=0),
) -> DiscoverTeamPage:
    """Ranked by score increase (latest team_score_history snapshot minus
    the one closest to WINDOW earlier), computed live rather than
    materialized — the number of teams is small enough that this is cheap,
    unlike sorting the whole clips table for /clips above. A team with no
    snapshot from that far back (brand new) is excluded rather than
    credited a fake increase-from-zero, which would otherwise let any
    freshly-founded team trivially top this list."""
    cutoff = datetime.now(UTC) - WINDOW
    teams = list(await db.scalars(select(Team).where(Team.founded_at.is_not(None))))

    rankings: list[tuple[Team, object, object]] = []
    for team in teams:
        latest = await db.scalar(
            select(TeamScoreHistory)
            .where(TeamScoreHistory.team_id == team.id)
            .order_by(TeamScoreHistory.captured_at.desc())
            .limit(1)
        )
        if latest is None or latest.score is None:
            continue
        baseline = await db.scalar(
            select(TeamScoreHistory)
            .where(TeamScoreHistory.team_id == team.id, TeamScoreHistory.captured_at <= cutoff)
            .order_by(TeamScoreHistory.captured_at.desc())
            .limit(1)
        )
        if baseline is None or baseline.score is None:
            continue
        rankings.append((team, latest.score, latest.score - baseline.score))

    rankings.sort(key=lambda r: r[2], reverse=True)
    page = rankings[offset : offset + limit]
    next_offset = offset + limit if offset + limit < len(rankings) else None

    items = [
        TeamRankingOut(team=team_brief(team), score=score, score_delta=delta)
        for team, score, delta in page
    ]
    return DiscoverTeamPage(items=items, next_offset=next_offset)
