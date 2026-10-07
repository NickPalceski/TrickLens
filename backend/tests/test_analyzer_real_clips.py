"""Stage A on the user's real clips (step 6b). Local only.

The clips are personal footage in backend/tests/fixtures/clips/, which is
gitignored, so these skip in CI and on any machine without them (see
test_video_details.md there for the user's own notes). They also skip
without the YOLOX weights, which only the worker image has.

Expected timings come from the clips' frames (contact sheets and
`make analyze-clip`), checked against the user's notes. Ranges, not exact
values: a detector or threshold tweak that moves a pop by one sample
(67ms at 15fps) shouldn't fail the suite.
"""

import os

import pytest

pytest.importorskip("cv2")

from app.analyzer import localize, media, stage_b  # noqa: E402
from app.config import get_settings  # noqa: E402

CLIPS = os.path.join(os.path.dirname(__file__), "fixtures", "clips")
MODEL = get_settings().yolox_model_path
POSE_MODEL = get_settings().pose_model_path


def _processed(tmp_path, name: str) -> tuple[str, media.VideoInfo]:
    src = os.path.join(CLIPS, name)
    if not os.path.exists(src):
        pytest.skip(f"real clip {name} not present (gitignored, local only)")
    if not os.path.exists(MODEL) or not os.path.exists(POSE_MODEL):
        pytest.skip("model weights not present — run in the worker image: make test-worker")
    out = str(tmp_path / "processed.mp4")
    media.transcode(src, out, media.probe(src))
    return out, media.probe(out)


def _stage_a(tmp_path, name: str) -> localize.StageAResult:
    path, info = _processed(tmp_path, name)
    return localize.analyze(path, info, MODEL)


def _stage_b(tmp_path, name: str) -> stage_b.TrickObservation:
    path, info = _processed(tmp_path, name)
    a = localize.analyze(path, info, MODEL)
    [w] = a.windows
    return stage_b.observe(path, info, a, w, MODEL, POSE_MODEL)


def test_tripod_kickflip_one_trick(tmp_path):
    """User's notes: pop ~1s, land ~2s, sketchy landing (feet off the
    bolts, a 6c concern). Frames: board up ~1.2s, apex ~1.47s, down ~1.6s."""
    r = _stage_a(tmp_path, "kickflip_sketchy_60fps.mov")
    [w] = r.windows
    assert 1000 <= w.pop_ms <= 1400
    assert 1300 <= w.apex_ms <= 1600
    assert 1450 <= w.land_ms <= 1800
    assert w.peak_elevation >= 0.2
    # Skater rolls in at ~0.8s; small in frame (the case the zoom pass exists for).
    assert r.skater_coverage >= 0.75
    assert 0.08 <= r.skater_height_frac <= 0.2


def test_followcam_bail_one_pop(tmp_path):
    """User's notes: pop ~1s, bail ~1.5s (board flipped, stepped off). The
    pop is found here; deciding it wasn't landed is 6c's roll-away check,
    so the window must reach past the bail."""
    r = _stage_a(tmp_path, "bail_60fps.mov")
    [w] = r.windows
    assert 900 <= w.pop_ms <= 1300
    assert w.end_ms >= 1500
    assert r.skater_coverage >= 0.95


def test_tripod_kickflip_stage_b(tmp_path):
    """Frames: feet back on the board ~1.62-1.65s. Stage A's 15fps landing
    (1.57s) is early; Stage B's 60fps touch-down must land after it."""
    o = _stage_b(tmp_path, "kickflip_sketchy_60fps.mov")
    assert o.fps == 60
    assert 1180 <= o.takeoff_ms <= 1320
    assert 1600 <= o.touchdown_ms <= 1720
    assert o.touchdown_ms > o.window.land_ms
    assert o.pose.found_frac >= 0.85 and o.pose.feet_visibility() >= 0.8
    assert o.board_found_frac >= 0.8


def test_followcam_bail_stage_b(tmp_path):
    """Frames: off the board ~1.08s, both feet down (without the board) at 1.33s."""
    o = _stage_b(tmp_path, "bail_60fps.mov")
    assert 1000 <= o.takeoff_ms <= 1150
    assert 1280 <= o.touchdown_ms <= 1400
    assert o.pose.found_frac >= 0.95
