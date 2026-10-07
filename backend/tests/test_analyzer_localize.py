"""Stage A pop finding (step 6b), on synthetic signals. No models, no video.

Each case builds the three per-sample series localize.analyze() would
produce (feet y, board centre y, skater height, all image pixels with y
growing downward) and checks which pops find_pops() reports. The numbers
mimic the real clips: a ~200px skater, ground around y=800, a few px of
detector jitter.

Worker image only (needs numpy/scipy). It skips under `make test`.
"""

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")  # localize imports detect, which needs OpenCV + onnxruntime

from app.analyzer.localize import (  # noqa: E402
    MIN_POP,
    SAMPLE_FPS,
    Signals,
    compute_elevation,
    find_pops,
)

H = 200.0  # skater height, px
GROUND = 800.0


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(seconds * SAMPLE_FPS)) * 1000.0 / SAMPLE_FPS


def _bump(t_ms: np.ndarray, center_ms: float, half_width_ms: float, height_px: float) -> np.ndarray:
    """A smooth hump: 0 outside center±half_width, `height_px` at the centre."""
    x = (t_ms - center_ms) / half_width_ms
    return np.where(np.abs(x) < 1, height_px * np.cos(x * np.pi / 2) ** 2, 0.0)


def _signals(t, feet_rise, board_rise, jitter=3.0, drift=None, seed=0) -> Signals:
    rng = np.random.default_rng(seed)
    base = GROUND + (drift if drift is not None else 0.0)
    return compute_elevation(
        Signals(
            t_ms=t,
            feet_y=base - feet_rise + rng.normal(0, jitter, len(t)),
            board_y=base
            - 15
            - board_rise
            + rng.normal(0, jitter * 2, len(t)),  # boards jitter more
            skater_h=np.full(len(t), H) + rng.normal(0, 4, len(t)),
        )
    )


def test_single_pop_found_with_sane_timing():
    t = _t(4)
    sig = _signals(t, _bump(t, 1500, 250, 0.35 * H), _bump(t, 1500, 250, 0.30 * H))
    [w] = find_pops(sig)
    assert 1400 <= w.apex_ms <= 1600
    assert w.pop_ms < w.apex_ms < w.land_ms
    assert 150 <= w.airtime_ms <= 500
    assert w.start_ms <= w.pop_ms - 300 and w.end_ms >= w.land_ms + 300
    assert w.peak_elevation == pytest.approx(0.30, abs=0.05)


def test_two_pops_in_a_line():
    t = _t(6)
    feet = _bump(t, 1500, 250, 0.3 * H) + _bump(t, 4000, 250, 0.3 * H)
    board = _bump(t, 1500, 250, 0.25 * H) + _bump(t, 4000, 250, 0.25 * H)
    apexes = [w.apex_ms for w in find_pops(_signals(t, feet, board))]
    assert len(apexes) == 2
    assert 1400 <= apexes[0] <= 1600 and 3900 <= apexes[1] <= 4100


def test_jitter_alone_is_not_a_pop():
    t = _t(5)
    assert find_pops(_signals(t, np.zeros(len(t)), np.zeros(len(t)), jitter=5.0)) == []


def test_carried_board_is_not_a_pop():
    """Board lifted high (picked up), feet stay on the ground."""
    t = _t(5)
    board = np.where((t > 1500) & (t < 2200), 0.6 * H, 0.0)
    assert find_pops(_signals(t, np.zeros(len(t)), board)) == []


def test_hop_off_the_board_is_not_a_pop():
    """Skater jumps, board stays on the ground."""
    t = _t(5)
    assert find_pops(_signals(t, _bump(t, 2000, 250, 0.3 * H), np.zeros(len(t)))) == []


def test_raised_ground_becomes_the_new_ground():
    """Board and feet both up and staying up (rolled onto a ledge/pad): the
    rolling ground estimate adopts the new level, so nothing *later* on the
    ledge looks airborne. The step itself can register once, which is right
    for an ollie-up. Terrain changes are a known Stage A limitation: drops
    and stair sets get the pop but not a trustworthy landing (docs/components/analyzer.md)."""
    t = _t(8)
    up = np.where(t > 2000, 0.3 * H, 0.0)
    windows = find_pops(_signals(t, up, up))
    assert len(windows) <= 1
    assert all(w.apex_ms < 3500 for w in windows)


def test_slow_ground_drift_is_not_a_pop_but_a_real_pop_on_it_is():
    """Skater riding toward the camera: ground moves 40px down over the clip
    (the follow-cam bail drifted ~23px in 1.4s)."""
    t = _t(5)
    drift = np.linspace(0, 40, len(t))
    flat = np.zeros(len(t))
    assert find_pops(_signals(t, flat, flat, drift=drift)) == []
    sig = _signals(t, _bump(t, 2500, 200, 0.2 * H), _bump(t, 2500, 200, 0.15 * H), drift=drift)
    assert len(find_pops(sig)) == 1


def test_board_missed_at_apex_still_finds_the_pop():
    """Mid-flip the board is edge-on and the detector loses it for a few
    samples. The feet stand in, and the board's rise either side counts."""
    t = _t(4)
    sig = Signals(
        t_ms=t,
        feet_y=GROUND - _bump(t, 1500, 400, 0.35 * H),
        board_y=GROUND - 15 - _bump(t, 1500, 400, 0.30 * H),
        skater_h=np.full(len(t), H),
    )
    apex = int(1500 * SAMPLE_FPS / 1000)
    # 5 samples: too long to interpolate over. The board is still seen
    # rising and falling either side, as on the real kickflip.
    sig.board_y[apex - 2 : apex + 3] = np.nan
    assert len(find_pops(compute_elevation(sig))) == 1


def test_pop_just_under_threshold_is_missed():
    """Documents the current floor (MIN_POP), which 6d calibrates."""
    t = _t(4)
    rise = _bump(t, 1500, 200, (MIN_POP * 0.7) * H)
    assert find_pops(_signals(t, rise, rise, jitter=0.5)) == []


def test_skater_absent_at_start_is_fine():
    """The tripod kickflip has no skater for its first 0.8s."""
    t = _t(4)
    sig = _signals(t, _bump(t, 2000, 250, 0.3 * H), _bump(t, 2000, 250, 0.25 * H))
    missing = t < 800
    for arr in (sig.feet_y, sig.board_y, sig.skater_h):
        arr[missing] = np.nan
    assert len(find_pops(compute_elevation(sig))) == 1
