"""Discover rankings rebuild (4d): the weekly top-clips snapshot
(`clip_rankings`) and one `team_score_history` row per founded team.

Same dev/prod trigger split as app/worker.py: locally, `make rankings` runs
`run()` on demand; in production (from step 5) an EventBridge rule invokes
`lambda_handler` on a schedule instead. Nothing here runs automatically in
dev — there's no scheduler in docker-compose to run it.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.clip import Clip
from app.models.discover import ClipRanking, TeamScoreHistory
from app.models.enums import ClipStatus
from app.models.social import ClipView, Comment, Like
from app.models.team import Team
from app.scoring import team_average_score

log = logging.getLogger("tricklens.rankings")

# Both Discover clip rankings and the team score delta use the same rolling
# window — clips published in the last 7 days, and "increase" meaning versus
# the snapshot closest to 7 days before the latest one.
WINDOW = timedelta(days=7)

# engagement_score = view_count*view + like_count*like + comment_count*comment.
# Comments weighted highest and views lowest: a view costs a viewer nothing,
# a like takes a single tap, a comment takes real effort to write — see the
# planning discussion in the conversation this shipped from. Tune freely;
# nothing else depends on the specific numbers.
ENGAGEMENT_WEIGHTS = {"view": 1, "like": 5, "comment": 10}


async def _rebuild_clip_rankings(db: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - WINDOW
    clips = list(
        await db.scalars(
            select(Clip).where(Clip.status == ClipStatus.PUBLISHED, Clip.published_at >= cutoff)
        )
    )
    clip_ids = [c.id for c in clips]

    likes: dict[Any, int] = {}
    comments: dict[Any, int] = {}
    views: dict[Any, int] = {}
    if clip_ids:
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
        views = dict(
            (
                await db.execute(
                    select(ClipView.clip_id, func.count())
                    .where(ClipView.clip_id.in_(clip_ids))
                    .group_by(ClipView.clip_id)
                )
            ).all()
        )

    # Fully replaced every run — this table has no meaning between rebuilds,
    # only as of the last one (see ClipRanking's docstring).
    await db.execute(delete(ClipRanking))
    now = datetime.now(UTC)
    for clip in clips:
        like_count = likes.get(clip.id, 0)
        comment_count = comments.get(clip.id, 0)
        view_count = views.get(clip.id, 0)
        engagement_score = (
            view_count * ENGAGEMENT_WEIGHTS["view"]
            + like_count * ENGAGEMENT_WEIGHTS["like"]
            + comment_count * ENGAGEMENT_WEIGHTS["comment"]
        )
        db.add(
            ClipRanking(
                clip_id=clip.id,
                steeze_score=clip.steeze_score,
                score_included=clip.score_included,
                like_count=like_count,
                comment_count=comment_count,
                view_count=view_count,
                engagement_score=engagement_score,
                captured_at=now,
            )
        )
    return len(clips)


async def _snapshot_team_scores(db: AsyncSession) -> int:
    teams = list(await db.scalars(select(Team).where(Team.founded_at.is_not(None))))
    now = datetime.now(UTC)
    for team in teams:
        score: Decimal | None = await team_average_score(db, team.id)
        db.add(TeamScoreHistory(team_id=team.id, score=score, captured_at=now))
    return len(teams)


async def run() -> tuple[int, int]:
    async with SessionLocal() as db:
        n_clips = await _rebuild_clip_rankings(db)
        n_teams = await _snapshot_team_scores(db)
        await db.commit()
    log.info("rankings rebuilt: %d clips ranked, %d team snapshots", n_clips, n_teams)
    return n_clips, n_teams


def lambda_handler(_event: dict[str, Any], _context: Any) -> dict[str, int]:
    """Production entrypoint (from step 5): one invocation per EventBridge
    schedule tick."""
    n_clips, n_teams = asyncio.run(run())
    return {"clips_ranked": n_clips, "teams_snapshotted": n_teams}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s | %(message)s"
    )
    asyncio.run(run())
