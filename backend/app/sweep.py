"""Fail clips stuck in `queued` or `analyzing` (step 6c-3).

The worker's last-receive give-up (app/worker.py) only covers a clip some
run already claimed. A message that fails every receive *before* the claim
(the database down, say) lands in the DLQ and leaves its clip `queued`
forever, with no message left to come back for it. So this marks any clip
still `queued` or `analyzing` after STUCK_AFTER `unanalyzable` with an
"analysis failed" analysis row, the same atomic UPDATE pattern as the
claim. Decided 2026-10-14: fail it, don't re-enqueue, since a retry would
need a counter to avoid looping forever.

STUCK_AFTER is well past everything SQS can still do with the message:
MAX_RECEIVES (3) × the 1800s visibility timeout is 90 minutes.

Same trigger as app/rankings.py, whose Lambda calls run() on every tick of
its schedule (every 30 minutes) — no infrastructure of its own. Locally,
`make sweep`. See docs/components/analyzer.md, Worker.
"""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, update

from app.analyzer.reasons import ANALYSIS_FAILED
from app.db import SessionLocal
from app.logs import configure_logging
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus

configure_logging()
log = logging.getLogger("tricklens.sweep")

STUCK_AFTER = timedelta(hours=2)
# No analyzer reached these clips, so no scorer's version applies.
MODEL_VERSION = "sweep"


async def run() -> int:
    """Fail every stuck clip. Returns how many."""
    async with SessionLocal() as db:
        ids = list(
            await db.scalars(
                update(Clip)
                .where(
                    Clip.status.in_([ClipStatus.QUEUED, ClipStatus.ANALYZING]),
                    Clip.updated_at < func.now() - STUCK_AFTER,
                )
                .values(status=ClipStatus.UNANALYZABLE, updated_at=func.now())
                .returning(Clip.id)
            )
        )
        for clip_id in ids:
            db.add(
                Analysis(
                    clip_id=clip_id,
                    model_version=MODEL_VERSION,
                    confidence=Decimal("0"),
                    failure_reason=ANALYSIS_FAILED,
                )
            )
        await db.commit()
    for clip_id in ids:
        log.warning(
            "sweep: clip %s -> unanalyzable (%s): stuck over %s",
            clip_id,
            ANALYSIS_FAILED,
            STUCK_AFTER,
        )
    return len(ids)


if __name__ == "__main__":
    print(f"swept {asyncio.run(run())} stuck clip(s)")
