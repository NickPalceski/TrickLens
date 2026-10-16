"""Measurements (measure.py) and the pipeline's per-trick crash handling
(pipeline.py), step 6c-3, on synthetic observations: hand-placed feet,
hips, world-landmark bodies and board boxes, no models, no video. The real
clips are covered in test_analyzer_real_clips.py (local only).

Worker image only (numpy). It skips under `make test`.
"""

import json
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from app.analyzer import calibration, landed, measure, pipeline  # noqa: E402
from app.analyzer import pose as P  # noqa: E402
from app.analyzer.detect import PERSON, SKATEBOARD, Detection  # noqa: E402
from app.analyzer.localize import TrickWindow  # noqa: E402
from app.analyzer.reasons import ANALYSIS_FAILED, TRICK_FAILED  # noqa: E402
from app.analyzer.stage_b import BOARD_EVERY, TrickObservation  # noqa: E402

FPS = 60.0
H = 200.0  # skater height, px
POP, APEX, LAND, TAKEOFF, TOUCHDOWN = 1000.0, 1200.0, 1380.0, 1000.0, 1400.0
DECK_Y = 750.0
BOARD_X = (240.0, 330.0)  # 0.45 skater heights long
# Foot centres (mean x of ankle, heel, toe; see _set_feet) on the bolt lines.
AT_BOLTS = tuple(BOARD_X[0] + b * (BOARD_X[1] - BOARD_X[0]) for b in measure.BOLTS)
CLIP_END = 5000.0


def _board(x1=BOARD_X[0], x2=BOARD_X[1]) -> Detection:
    return Detection(SKATEBOARD, 0.8, x1, DECK_Y, x2, DECK_Y + 25)


def _set_feet(img: np.ndarray, rows, feet: tuple[float, float]) -> None:
    """Both feet standing at DECK_Y, each foot's centre at the given x."""
    offsets = ((0, -10), (-6, -4), (6, 0))  # ankle, heel, toe: centre = x
    for x, points in zip(feet, (landed.LEFT, landed.RIGHT), strict=True):
        for p, (dx, dy) in zip(points, offsets, strict=True):
            img[rows, p] = (x + dx, DECK_Y + dy, 0.9)


def _standing_world() -> np.ndarray:
    """A standing body in metres, hips at the origin, y down: torso 0.5,
    so arm_ratio 0.54 (hands by the hips) and leg_ratio 1.7."""
    w = np.zeros((P.N_LANDMARKS, 3))
    w[P.L_HIP], w[P.R_HIP] = (0.1, 0, 0), (-0.1, 0, 0)
    w[P.L_SHOULDER], w[P.R_SHOULDER] = (0.15, -0.5, 0), (-0.15, -0.5, 0)
    w[P.L_WRIST], w[P.R_WRIST] = (0.25, 0.1, 0), (-0.25, 0.1, 0)
    w[P.L_ANKLE], w[P.R_ANKLE] = (0.1, 0.85, 0), (-0.1, 0.85, 0)
    return w


def _obs(feet=AT_BOLTS, end_ms=LAND + 1300, touchdown=TOUCHDOWN) -> TrickObservation:
    """A clean landed trick: feet on the board's bolts throughout, the board
    sampled every BOARD_EVERY frames from the pop on, feet 0.3 skater
    heights up at the apex. Tests then edit the arrays in place."""
    window = TrickWindow(POP, APEX, LAND, POP - 400, end_ms, 0.25)
    t = np.arange(np.ceil(window.start_ms * FPS / 1000), np.floor(end_ms * FPS / 1000) + 1)
    t = t * 1000 / FPS
    n = len(t)
    img = np.zeros((n, P.N_LANDMARKS, 3))
    img[:, :, :2] = (300, 600)
    img[:, :, 2] = 0.9
    img[:, [P.L_HIP, P.R_HIP], 1] = DECK_Y - 0.5 * H
    _set_feet(img, slice(None), feet)
    world = np.repeat(_standing_world()[None], n, axis=0)
    elev = np.where(
        (t > TAKEOFF) & (t < TOUCHDOWN), 0.3 * (1 - np.abs(t - APEX) / (APEX - TAKEOFF)), 0.0
    )
    person = Detection(PERSON, 0.9, 220, DECK_Y - H, 350, DECK_Y)
    return TrickObservation(
        window=window,
        fps=FPS,
        pose=P.PoseTrack(t, img, world, np.ones(n, bool)),
        skater=[person] * n,
        board={r: _board() for r, tt in enumerate(t) if tt >= POP - 200 and r % BOARD_EVERY == 0},
        skater_h=H,
        feet_elev=elev,
        takeoff_ms=TAKEOFF,
        touchdown_ms=touchdown,
    )


def _rows(obs, lo, hi):
    return np.flatnonzero((obs.pose.t_ms >= lo) & (obs.pose.t_ms < hi))


def _m(obs, clip_end=CLIP_END) -> dict:
    return measure.measure(obs, TOUCHDOWN, clip_end)


# --- pop ---------------------------------------------------------------------


def test_pop_is_the_feet_peak_in_the_air():
    m = _m(_obs())
    assert m["pop_height"] == pytest.approx(0.3, abs=0.01)
    assert m["airtime_ms"] == TOUCHDOWN - TAKEOFF


def test_pop_falls_back_to_stage_a_without_pose_in_the_air():
    o = _obs()
    o.feet_elev[:] = np.nan
    assert _m(o)["pop_height"] == 0.25


# --- landing stability ---------------------------------------------------------


def test_a_still_landing_settles_at_once():
    m = _m(_obs())
    assert m["settle_ms"] == 0.0
    assert m["torso_sway_deg"] == pytest.approx(0.0, abs=0.01)
    assert m["arm_flail"] == pytest.approx(0.0, abs=0.01)


def test_bobbing_hips_settle_late():
    o = _obs()
    rows = _rows(o, TOUCHDOWN, TOUCHDOWN + 350)
    o.pose.image[rows[::2], P.L_HIP, 1] += 0.1 * H  # every other frame: a wobble
    o.pose.image[rows[::2], P.R_HIP, 1] += 0.1 * H
    assert 300 <= _m(o)["settle_ms"] <= 350


def test_swaying_torso_and_flailing_arms_are_measured():
    o = _obs()
    rows = _rows(o, TOUCHDOWN + 100, TOUCHDOWN + 600)
    lean = np.where(np.arange(len(rows)) % 10 < 5, 0.3, -0.3)  # ±31° back and forth
    o.pose.world[rows, P.L_SHOULDER, 0] += lean
    o.pose.world[rows, P.R_SHOULDER, 0] += lean
    o.pose.world[rows[::3], P.L_WRIST] = (0.9, -0.6, 0)  # an arm thrown up and out
    m = _m(o)
    assert m["torso_sway_deg"] > 20
    assert m["arm_flail"] > 1.0


# --- roll-away -------------------------------------------------------------------


def test_riding_away_on_the_board():
    m = _m(_obs())
    assert m["rollaway_on_board_frac"] == 1.0 and m["foot_down"] is False
    assert m["rollaway_judged"] >= measure.MIN_ROLLAWAY_JUDGED


def test_a_foot_off_the_board_during_the_roll_away_is_a_foot_down():
    o = _obs()
    rows = _rows(o, TOUCHDOWN + 800, TOUCHDOWN + 1300)
    _set_feet(o.pose.image, rows, (AT_BOLTS[0], AT_BOLTS[1] + 0.3 * H))  # front foot stepped off
    m = _m(o)
    assert m["foot_down"] is True and m["rollaway_on_board_frac"] < 1.0
    assert calibration.subscores(m)["roll_away"] <= calibration.FOOT_DOWN_CAP


def test_roll_away_is_na_when_the_clip_ends_too_soon():
    m = _m(_obs(), clip_end=TOUCHDOWN + 800)
    assert m["rollaway_ms"] == 200.0
    assert m["rollaway_on_board_frac"] is None and m["foot_down"] is None
    assert calibration.subscores(m)["roll_away"] is None


# --- stomp ---------------------------------------------------------------------


def test_feet_over_the_bolts_stomp_it():
    m = _m(_obs())
    assert m["stomp_error"] == pytest.approx(0.0, abs=0.01)
    assert m["board_len"] == pytest.approx(0.45, abs=0.01)


def test_feet_on_the_nose_and_tail_are_off_the_bolts():
    m = _m(_obs(feet=(BOARD_X[0] + 4, BOARD_X[1] - 4)))
    assert m["stomp_error"] > 0.2


def test_stomp_is_na_for_a_board_seen_end_on():
    o = _obs(feet=(265.0, 275.0))
    for r in o.board:
        o.board[r] = _board(255, 285)  # 0.15 skater heights: end-on
    m = _m(o)
    assert m["board_len"] == pytest.approx(0.15, abs=0.01)
    assert m["stomp_error"] is None and calibration.subscores(m)["stomp"] is None


# --- compactness ------------------------------------------------------------------


def test_tucked_legs_in_the_air_are_compact():
    o = _obs()
    stand = _m(o)
    rows = _rows(o, TAKEOFF, TOUCHDOWN)
    o.pose.world[rows, P.L_ANKLE, 1] = o.pose.world[rows, P.R_ANKLE, 1] = 0.5
    tuck = _m(o)
    assert stand["leg_ratio"] == pytest.approx(1.7, abs=0.01)
    assert tuck["leg_ratio"] < 1.1
    assert stand["arm_ratio"] == pytest.approx(0.54, abs=0.01)


# --- catch -------------------------------------------------------------------------


def test_feet_that_never_leave_the_board_have_no_catch():
    m = _m(_obs())
    assert m["separated"] is False
    assert m["catch_ms"] is None and calibration.subscores(m)["catch"] is None


def test_the_catch_is_when_both_feet_are_back_on_the_board():
    o = _obs()
    flick = _rows(o, TAKEOFF + 50, TAKEOFF + 250)  # front foot kicks off the side
    _set_feet(o.pose.image, flick, (AT_BOLTS[0], BOARD_X[1] + 0.25 * H))
    m = _m(o)
    assert m["separated"] is True
    # Back on from 1250ms; the first board sample after that is at 1266.7ms.
    assert m["catch_ms"] == pytest.approx(TOUCHDOWN - 1266.7, abs=1)
    assert m["catch_frac"] == pytest.approx(m["catch_ms"] / (TOUCHDOWN - TAKEOFF), abs=0.01)


def test_a_partial_board_box_before_touch_down_doesnt_undo_the_catch():
    """The 6c-3 prod check: one box around only part of the board, a
    sample before touch-down, read as both feet off and reset the catch to
    touch-down itself."""
    o = _obs()
    _set_feet(o.pose.image, _rows(o, TAKEOFF + 50, TAKEOFF + 250), (AT_BOLTS[0], 400.0))
    clean = _m(o)
    last = max(r for r, tt in enumerate(o.pose.t_ms) if r in o.board and tt < TOUCHDOWN)
    o.board[last] = _board(BOARD_X[0], BOARD_X[0] + 40)  # 0.2 skater heights: a fragment
    m = _m(o)
    assert m["partial_boards"] == 1
    assert m["catch_ms"] == clean["catch_ms"] > 100


def test_a_late_catch_scores_lower_than_an_early_one():
    early, late = _obs(), _obs()
    _set_feet(early.pose.image, _rows(early, 1050, 1150), (AT_BOLTS[0], 400.0))
    _set_feet(late.pose.image, _rows(late, 1050, 1380), (AT_BOLTS[0], 400.0))
    s_early = calibration.subscores(_m(early))["catch"]
    s_late = calibration.subscores(_m(late))["catch"]
    assert s_early > s_late


# --- the pipeline: crashes stay with their trick --------------------------------


@pytest.fixture
def fake_stages(monkeypatch):
    """pipeline.analyze with media, Stage A and Stage B replaced: two
    tricks, whose observations each test chooses (an exception = a crash)."""
    w1 = TrickWindow(POP, APEX, LAND, POP - 400, LAND + 1300, 0.25)
    w2 = TrickWindow(POP + 3000, APEX + 3000, LAND + 3000, POP + 2600, LAND + 4300, 0.4)
    stage_a = SimpleNamespace(
        windows=[w1, w2],
        brightness=120.0,
        skater_height_frac=0.14,
        skater_coverage=0.9,
        timings_s={},
    )
    info = SimpleNamespace(duration_ms=8000, output_fps=60, width=720, height=1280)
    outcomes: list = []

    def observe(_path, _info, _a, window, *_paths):
        out = outcomes[[w1, w2].index(window)]
        if isinstance(out, Exception):
            raise out
        return out

    monkeypatch.setattr(pipeline.media, "probe", lambda _p: info)
    monkeypatch.setattr(pipeline.localize, "analyze", lambda *_a: stage_a)
    monkeypatch.setattr(pipeline.stage_b, "observe", observe)
    return outcomes


def test_one_trick_crashing_leaves_the_other_scored(fake_stages):
    fake_stages[:] = [_obs(), RuntimeError("boom")]
    res = pipeline.analyze("x.mp4", "y", "p")
    assert res.failure_reason is None
    assert res.steeze_score is not None and res.subscores[1] is None
    details = res.details()
    json.dumps(details, allow_nan=False)  # Postgres JSONB rejects NaN
    assert [t["outcome"] for t in details["tricks"]] == ["landed", TRICK_FAILED]
    assert details["tricks"][0]["measurements"]["stomp_error"] is not None
    assert res.thumb_at_ms == round(APEX + 3000)  # the bigger pop's apex


def test_measuring_the_only_landed_trick_crashing_fails_the_clip(fake_stages, monkeypatch):
    fake_stages[:] = [_obs(), RuntimeError("boom")]

    def broken(*_a):
        raise ValueError("measurement bug")

    monkeypatch.setattr(pipeline.measure, "measure", broken)
    res = pipeline.analyze("x.mp4", "y", "p")
    assert res.failure_reason == ANALYSIS_FAILED
    assert res.breakdown is None and res.steeze_score is None
    assert [t.outcome for t in res.verdict.tricks] == [TRICK_FAILED, TRICK_FAILED]


def test_the_breakdown_averages_the_landed_tricks(fake_stages):
    tucked = _obs()
    rows = _rows(tucked, TAKEOFF, TOUCHDOWN)
    tucked.pose.world[rows, P.L_ANKLE, 1] = tucked.pose.world[rows, P.R_ANKLE, 1] = 0.5
    fake_stages[:] = [_obs(), tucked]
    res = pipeline.analyze("x.mp4", "y", "p")
    a, b = res.subscores
    assert res.breakdown["compactness"] == pytest.approx(
        (a["compactness"] + b["compactness"]) / 2, abs=0.06
    )
    assert res.breakdown["catch"] is None  # no catch on either
    present = [v for v in res.breakdown.values() if v is not None]
    assert res.steeze_score == pytest.approx(sum(present) / len(present), abs=0.06)
