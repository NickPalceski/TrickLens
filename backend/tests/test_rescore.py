"""app/rescore.py (step 6d): rescoring stored analyses from their
measurements, against real Postgres with the same sync, DB-only connection
the GitHub Actions job uses. Runs in the API image.

The dev database is shared state, so these assert only on their own clips,
never on how many clips a run touched (see CLAUDE.md's gotcha).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import rescore
from app.analyzer import calibration
from app.config import get_migration_settings
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.models.user import User

MEASURED = {
    "pop_height": 0.38, "settle_ms": 50.0, "torso_sway_deg": 2.05, "arm_flail": 0.62,
    "rollaway_on_board_frac": 1.0, "foot_down": False, "stomp_error": 0.12,
    "arm_ratio": 1.93, "leg_ratio": 1.21, "catch_frac": 0.5,
}  # fmt: skip
OLD = "steeze-test-old"


@pytest.fixture(scope="module")
def db():
    engine = create_engine(get_migration_settings().sync_url)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _clip(db, status=ClipStatus.PUBLISHED, version=OLD, details="measured") -> uuid.UUID:
    user = User(cognito_sub=f"test-{uuid.uuid4()}", username=f"r{uuid.uuid4().hex[:10]}")
    db.add(user)
    db.flush()
    clip = Clip(user_id=user.id, status=status, s3_key=f"raw/{uuid.uuid4()}.mp4")
    clip.steeze_score = Decimal("50.0")
    db.add(clip)
    db.flush()
    tricks = [{"outcome": "landed", "measurements": MEASURED, "subscores": {}}]
    if details == "stub":
        tricks = [{"outcome": "landed", "measurements": None, "subscores": {"pop": 80.0}}]
    db.add(
        Analysis(
            clip_id=clip.id,
            model_version=version,
            confidence=Decimal("0.90"),
            steeze_breakdown={},
            details=None if details is None else {"schema": 1, "tricks": tricks},
        )
    )
    db.commit()
    return clip.id


def _analyses(db, clip_id):
    db.expire_all()
    return list(
        db.scalars(
            select(Analysis).where(Analysis.clip_id == clip_id).order_by(Analysis.created_at)
        )
    )


def test_dry_run_lists_without_writing(db):
    clip_id = _clip(db)
    changes = {c.clip_id: c for c in rescore.run(db, apply=False)}
    expected = calibration.aggregate([calibration.subscores(MEASURED)])[1]
    assert changes[clip_id].old_version == OLD and changes[clip_id].new_score == expected
    assert [a.model_version for a in _analyses(db, clip_id)] == [OLD]


def test_apply_appends_a_new_analysis_and_updates_the_score_once(db):
    clip_id = _clip(db)
    rescore.run(db, apply=True)
    old, new = _analyses(db, clip_id)
    breakdown, steeze = calibration.aggregate([calibration.subscores(MEASURED)])
    assert (old.model_version, new.model_version) == (OLD, calibration.MODEL_VERSION)
    assert new.steeze_breakdown == breakdown and new.details["rescored_from"] == OLD
    assert db.get(Clip, clip_id).steeze_score == Decimal(str(steeze))
    # Idempotent: the second run leaves it alone.
    assert clip_id not in {c.clip_id for c in rescore.run(db, apply=True)}
    assert len(_analyses(db, clip_id)) == 2


def test_clips_it_cant_or_shouldnt_rescore_are_left_alone(db):
    current = _clip(db, version=calibration.MODEL_VERSION)
    stub = _clip(db, details="stub")
    no_details = _clip(db, details=None)
    unanalyzable = _clip(db, status=ClipStatus.UNANALYZABLE)
    touched = {c.clip_id for c in rescore.run(db, apply=False)}
    assert not touched & {current, stub, no_details, unanalyzable}
