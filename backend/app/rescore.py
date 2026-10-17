"""Rescore stored analyses with the current calibration.py (step 6d).

    python -m app.rescore            # dry run: list old -> new, write nothing
    python -m app.rescore --apply    # write them

When 6d changes calibration.py's constants and bumps its MODEL_VERSION,
every clip analyzed before the change still carries a score from the old
constants, so old and new clips would be ranked against each other on
different scales (Discover, profile and team averages). The raw
measurements behind each score are stored in `analyses.details`, so this
recomputes the subscores from them, with no video: the raw uploads expire
after 7 days anyway.

For each `analyzed` or `published` clip whose latest analysis was scored
by another model version and has measurements, it appends a new analyses
row (analyses are never edited, so the old score stays as history) with
the current MODEL_VERSION and updates `clips.steeze_score`. Verdicts
(landed, bailed) don't change: those need the video. Running it twice is
harmless: the second run finds nothing to do. Discover's snapshot picks
the new scores up on its next rebuild (every 30 minutes in prod).

Database only, synchronous, through the same DB-only settings Alembic uses
(get_migration_settings), because in prod it runs from a GitHub Actions
runner with nothing but ALEMBIC_DATABASE_URL (.github/workflows/rescore.yml).
See docs/components/analyzer.md, Calibration (6d).
"""

import argparse
import copy
import logging
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload

from app.analyzer import calibration
from app.config import get_migration_settings
from app.logs import configure_logging
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus

configure_logging()
log = logging.getLogger("tricklens.rescore")

SCORED = (ClipStatus.ANALYZED, ClipStatus.PUBLISHED)


@dataclass
class Change:
    clip_id: uuid.UUID
    old_version: str
    old_score: Decimal | None
    new_score: float


def rescored(details: dict) -> tuple[dict, dict, float] | None:
    """(new details, breakdown, steeze) from stored measurements, or None
    when no landed trick has any."""
    new = copy.deepcopy(details)
    landed = []
    for t in new.get("tricks", []):
        if t.get("outcome") == "landed" and t.get("measurements"):
            t["subscores"] = calibration.subscores(t["measurements"])
            landed.append(t["subscores"])
    if not landed:
        return None
    breakdown, steeze = calibration.aggregate(landed)
    if steeze is None:
        return None
    return new, breakdown, steeze


def run(db: Session, apply: bool) -> list[Change]:
    """Find (and with `apply`, write) every clip to rescore."""
    clips = db.scalars(
        select(Clip).where(Clip.status.in_(SCORED)).options(selectinload(Clip.analyses))
    )
    changes = []
    for clip in clips:
        latest = clip.analyses[0] if clip.analyses else None
        if latest is None or latest.model_version == calibration.MODEL_VERSION:
            continue
        result = rescored(latest.details or {})
        if result is None:  # stub, or no measurements (before 6c-3)
            continue
        details, breakdown, steeze = result
        details["rescored_from"] = latest.model_version
        changes.append(Change(clip.id, latest.model_version, clip.steeze_score, steeze))
        if apply:
            db.add(
                Analysis(
                    clip_id=clip.id,
                    model_version=calibration.MODEL_VERSION,
                    confidence=latest.confidence,
                    steeze_breakdown=breakdown,
                    failure_reason=None,
                    details=details,
                )
            )
            clip.steeze_score = Decimal(str(steeze))
    if apply:
        db.commit()
    return changes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Rescore stored analyses with calibration.py.")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args(argv)
    engine = create_engine(get_migration_settings().sync_url, pool_pre_ping=True)
    with Session(engine) as db:
        changes = run(db, args.apply)
    for c in changes:
        print(f"{c.clip_id}  {c.old_version}  {c.old_score} -> {c.new_score}")
    verb = "rescored" if args.apply else "would rescore (dry run)"
    print(f"{verb} {len(changes)} clip(s) to {calibration.MODEL_VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
