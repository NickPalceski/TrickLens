"""The landed check and the confidence gate (6c-2), on synthetic
observations: hand-placed feet and board boxes, no models, no video. The
real clips are covered in test_analyzer_real_clips.py (local only).

Worker image only (numpy). It skips under `make test`.
"""

from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")

from app.analyzer import gate, landed  # noqa: E402
from app.analyzer import pose as P  # noqa: E402
from app.analyzer.detect import PERSON, SKATEBOARD, Detection  # noqa: E402
from app.analyzer.localize import TrickWindow  # noqa: E402
from app.analyzer.reasons import (  # noqa: E402
    BODY_NOT_VISIBLE,
    CLIP_ENDS,
    LEFT_FRAME,
    NO_AIRTIME,
    NO_LANDING,
    TOO_DARK,
    TOO_FAR,
)
from app.analyzer.stage_b import BOARD_EVERY, TrickObservation  # noqa: E402

H = 200.0  # skater height, px
POP, LAND, TOUCHDOWN = 1000.0, 1380.0, 1400.0
DECK_Y = 750.0  # board top; the feet stand on it


def _board(x1: float, x2: float, y1: float = DECK_Y) -> Detection:
    return Detection(SKATEBOARD, 0.8, x1, y1, x2, y1 + 25)


ON_BOARD = _board(240, 330)  # 90px = 0.45 skater heights, a real board's length


def _obs(
    feet=(260.0, 310.0),
    board=ON_BOARD,
    fps=60.0,
    touchdown: float | None = TOUCHDOWN,
    end_ms=LAND + 800,
    pose_found=True,
    feet_vis=0.9,
    skater=True,
) -> TrickObservation:
    """One trick. `feet`: (left x, right x) after touch-down, both standing
    at DECK_Y. `board`: the board box after touch-down (None: not seen)."""
    window = TrickWindow(POP, 1200, LAND, POP - 400, end_ms, 0.3)
    t = np.arange(np.ceil(window.start_ms * fps / 1000), np.floor(end_ms * fps / 1000) + 1)
    t = t * 1000 / fps
    n = len(t)
    img = np.zeros((n, P.N_LANDMARKS, 3))
    img[:, :, :2] = (300, 600)
    img[:, :, 2] = 0.9
    for x, points in zip(feet, (landed.LEFT, landed.RIGHT), strict=True):
        for p, (dx, dy) in zip(points, ((0, -10), (-6, -4), (8, 0)), strict=True):
            img[:, p] = (x + dx, DECK_Y + dy, feet_vis)
    found = np.full(n, pose_found)
    if not pose_found:
        img[:] = np.nan
    pose = P.PoseTrack(t, img, img.copy(), found)
    person = Detection(PERSON, 0.9, 220, DECK_Y - H, 350, DECK_Y)
    boards = {
        row: board if tt > LAND else _board(240, 330, DECK_Y - 60)
        for row, tt in enumerate(t)
        if tt >= POP - 200 and row % BOARD_EVERY == 0
    }
    return TrickObservation(
        window=window,
        fps=fps,
        pose=pose,
        skater=[person if skater else None] * n,
        board=boards,
        skater_h=H,
        feet_elev=np.zeros(n),
        takeoff_ms=POP,
        touchdown_ms=touchdown,
    )


CLIP_END = 5000.0


# --- the landed check --------------------------------------------------------


def test_both_feet_on_the_board_is_landed():
    c = landed.check_landing(_obs(), CLIP_END)
    assert c.verdict == landed.Verdict.LANDED
    assert c.on_board == c.judged == c.sampled > 10
    assert c.stance == pytest.approx(0.25, abs=0.01)


def test_wide_stance_is_a_bail_even_if_the_board_box_agrees():
    """Feet 0.6 skater heights apart can't both be on a board."""
    c = landed.check_landing(_obs(feet=(200.0, 320.0), board=_board(180, 340)), CLIP_END)
    assert c.verdict == landed.Verdict.BAILED
    assert c.stance > landed.MAX_STANCE


def test_board_away_from_the_feet_is_a_bail():
    c = landed.check_landing(_obs(board=_board(500, 590)), CLIP_END)
    assert c.verdict == landed.Verdict.BAILED
    assert c.on_board == 0 and c.judged == c.sampled


def test_board_far_below_the_feet_is_not_under_them():
    c = landed.check_landing(_obs(board=_board(240, 330, DECK_Y + 0.4 * H)), CLIP_END)
    assert c.verdict == landed.Verdict.BAILED


def test_an_implausibly_long_board_box_is_ignored():
    """The bail's trap: one box around the board plus something beside it,
    wide enough for both feet. It must not count as evidence of a landing."""
    c = landed.check_landing(_obs(board=_board(200, 360)), CLIP_END)  # 0.8 skater heights
    assert c.implausible_boards == c.sampled and c.judged == 0
    assert c.verdict == landed.Verdict.UNCLEAR and c.unclear_reason == NO_LANDING


def test_board_never_seen_after_landing_is_unclear():
    c = landed.check_landing(_obs(board=None), CLIP_END)
    assert c.verdict == landed.Verdict.UNCLEAR and c.unclear_reason == NO_LANDING


def test_clip_ending_right_after_the_landing_is_unclear():
    c = landed.check_landing(_obs(), clip_end_ms=TOUCHDOWN + 300)
    assert c.verdict == landed.Verdict.UNCLEAR and c.unclear_reason == CLIP_ENDS


def test_without_a_refined_touchdown_stage_a_landing_stands_in():
    c = landed.check_landing(_obs(touchdown=None), CLIP_END)
    assert c.touchdown_ms == LAND and c.verdict == landed.Verdict.LANDED


def test_low_visibility_feet_are_not_judged():
    c = landed.check_landing(_obs(feet_vis=0.2), CLIP_END)
    assert c.judged == 0 and c.stance is None
    assert c.verdict == landed.Verdict.UNCLEAR


# --- the gate ----------------------------------------------------------------


def _stage_a(n_windows=1, brightness=120.0, height=0.14):
    windows = [object()] * n_windows
    return SimpleNamespace(windows=windows, brightness=brightness, skater_height_frac=height)


def test_a_landed_trick_passes_with_good_confidence():
    v = gate.assess_clip(_stage_a(), [_obs()], CLIP_END)
    assert v.failure_reason is None and len(v.landed) == 1
    assert 0.8 <= v.confidence <= 1.0


def test_a_lone_bail_fails_with_no_landed_trick():
    v = gate.assess_clip(_stage_a(), [_obs(board=_board(500, 590))], CLIP_END)
    assert v.failure_reason == NO_LANDING
    assert v.tricks[0].outcome == "bailed"


def test_a_bail_in_a_line_is_left_out_not_failed():
    v = gate.assess_clip(_stage_a(2), [_obs(board=_board(500, 590)), _obs()], CLIP_END)
    assert v.failure_reason is None
    assert [t.outcome for t in v.tricks] == ["bailed", "landed"]
    assert v.confidence == v.landed[0].confidence


def test_the_most_actionable_reason_wins():
    """A bail and a trick that left the frame: the user can fix the second."""
    v = gate.assess_clip(_stage_a(2), [_obs(board=_board(500, 590)), _obs(skater=False)], CLIP_END)
    assert v.failure_reason == LEFT_FRAME


def test_pose_losing_the_skater_is_body_not_visible():
    v = gate.assess_clip(_stage_a(), [_obs(pose_found=False)], CLIP_END)
    assert v.failure_reason == BODY_NOT_VISIBLE


def test_clip_ends_reason_reaches_the_clip():
    v = gate.assess_clip(_stage_a(), [_obs()], clip_end_ms=TOUCHDOWN + 300)
    assert v.failure_reason == CLIP_ENDS


def test_no_pops_is_no_clean_airtime():
    assert gate.assess_clip(_stage_a(0), [], CLIP_END).failure_reason == NO_AIRTIME


def test_a_tiny_skater_fails_as_too_far_even_when_landed():
    v = gate.assess_clip(_stage_a(height=0.05), [_obs()], CLIP_END)
    assert v.failure_reason == TOO_FAR
    assert gate.assess_clip(_stage_a(0, height=0.05), [], CLIP_END).failure_reason == TOO_FAR


def test_darkness_explains_a_failure_but_never_fails_a_clip_alone():
    assert gate.assess_clip(_stage_a(brightness=20), [_obs()], CLIP_END).failure_reason is None
    assert gate.assess_clip(_stage_a(0, brightness=20), [], CLIP_END).failure_reason == TOO_DARK
    bail = [_obs(board=_board(500, 590))]
    assert gate.assess_clip(_stage_a(brightness=20), bail, CLIP_END).failure_reason == TOO_DARK


def test_30fps_footage_lowers_confidence():
    c60 = gate.assess_clip(_stage_a(), [_obs()], CLIP_END).confidence
    c30 = gate.assess_clip(_stage_a(), [_obs(fps=30.0)], CLIP_END).confidence
    assert c30 < c60 and c30 >= 0.5
