"""Stage B (6c-1): windowed decoding, feet signal, take-off/touch-down.

No models: the contact refinement is fed synthetic feet trajectories, and
the windowed decode is checked against ffmpeg test video. Pose/board on
real footage is covered by test_analyzer_real_clips.py (local only).

Worker image only (numpy/OpenCV/ffmpeg). It skips under `make test`.
"""

import shutil
import subprocess
from types import SimpleNamespace

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

from app.analyzer import pose as P  # noqa: E402
from app.analyzer.detect import PERSON, Detection  # noqa: E402
from app.analyzer.frames import iter_frames  # noqa: E402
from app.analyzer.localize import TrickWindow  # noqa: E402
from app.analyzer.stage_b import (  # noqa: E402
    FEET_OFF,
    lowest_foot_y,
    refine_contacts,
    skater_at,
)

FPS = 60.0
H = 200.0  # skater height, px


def _window(pop=1000.0, land=1400.0) -> TrickWindow:
    return TrickWindow(
        pop_ms=pop, apex_ms=(pop + land) / 2, land_ms=land,
        start_ms=pop - 400, end_ms=land + 600, peak_elevation=0.3,
    )  # fmt: skip


def _t(w: TrickWindow) -> np.ndarray:
    first = np.ceil(w.start_ms * FPS / 1000)
    last = np.floor(w.end_ms * FPS / 1000)
    return np.arange(first, last + 1) * 1000 / FPS


def _airborne(t, off_ms, on_ms, height_px, base=800.0, after=None):
    """Lowest-foot y: on the deck at `base`, a hump between off/on, then at
    `after` (default: back on the deck)."""
    y = np.full(len(t), base)
    air = (t >= off_ms) & (t < on_ms)
    x = (t[air] - off_ms) / (on_ms - off_ms)
    y[air] = base - height_px * np.sin(np.pi * x)
    if after is not None:
        y[t >= on_ms] = after
    return y


def test_refine_finds_takeoff_and_touchdown():
    w = _window()
    t = _t(w)
    y = _airborne(t, 1050, 1450, 0.35 * H)  # Stage A was ~50ms early, like the kickflip
    elev, takeoff, touchdown = refine_contacts(t, y, H, w)
    assert takeoff == pytest.approx(1050, abs=1000 / FPS + 1)
    assert touchdown == pytest.approx(1450, abs=2 * 1000 / FPS + 1)
    assert np.nanmax(elev) == pytest.approx(0.35, abs=0.02)


def test_refine_handles_landing_on_the_ground_after_a_bail():
    """Bail: the feet come down on the ground, lower than the deck."""
    w = _window()
    t = _t(w)
    y = _airborne(t, 1000, 1300, 0.2 * H, base=800, after=812)
    _, takeoff, touchdown = refine_contacts(t, y, H, w)
    assert takeoff is not None and touchdown == pytest.approx(1300, abs=2 * 1000 / FPS + 1)


def test_refine_bridges_missed_pose_frames_in_the_air():
    w = _window()
    t = _t(w)
    y = _airborne(t, 1050, 1450, 0.35 * H)
    y[(t > 1180) & (t < 1260)] = np.nan  # pose lost mid-flip
    _, takeoff, touchdown = refine_contacts(t, y, H, w)
    assert takeoff == pytest.approx(1050, abs=17) and touchdown == pytest.approx(1450, abs=34)


def test_refine_gives_up_when_the_feet_never_leave():
    w = _window()
    t = _t(w)
    y = np.full(len(t), 800.0) + np.random.default_rng(0).normal(0, 1.5, len(t))
    _, takeoff, touchdown = refine_contacts(t, y, H, w)
    assert takeoff is None and touchdown is None
    assert FEET_OFF * H > 3 * 1.5  # the threshold sits well above that jitter


def test_lowest_foot_ignores_low_visibility_points():
    img = np.zeros((2, P.N_LANDMARKS, 3))
    img[:, :, 2] = 0.9
    img[0, P.L_HEEL] = (0, 810, 0.9)
    img[0, P.R_TOE] = (0, 900, 0.2)  # lower, but not trusted
    img[1, list(P.FEET), 2] = 0.1  # nothing trusted
    track = P.PoseTrack(np.array([0.0, 16.7]), img, img.copy(), np.array([True, True]))
    y = lowest_foot_y(track)
    assert y[0] == 810 and np.isnan(y[1])


def test_skater_box_interpolates_between_stage_a_samples():
    a = Detection(PERSON, 0.9, 100, 500, 140, 700)
    b = Detection(PERSON, 0.9, 130, 500, 170, 700)
    stage_a = SimpleNamespace(skater=[a, b, None])
    mid = skater_at(stage_a, 1000 / 15 / 2)  # halfway between samples 0 and 1
    assert mid.x1 == pytest.approx(115)
    assert skater_at(stage_a, 2 * 1000 / 15) is None


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg (worker image)")
def test_windowed_decode_matches_full_decode(tmp_path):
    """Stage B decodes only a window. Its frames must be the same frames,
    with the same timestamps, as a whole-clip decode, or Stage A and B
    disagree about when things happened."""
    path = str(tmp_path / "src.mp4")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc2=size=160x120:rate=60:duration=2",
         "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-g", "30", path],
        check=True,
    )  # fmt: skip
    full = {round(f.t_ms, 3): f.image for f in iter_frames(path, 160, 120, 60)}
    window = list(iter_frames(path, 160, 120, 60, start_ms=505, end_ms=900))
    assert window[0].t_ms == pytest.approx(516.667, abs=0.01)  # first 60fps tick >= 505
    assert window[-1].t_ms <= 900 + 1000 / 60
    for f in window:
        assert np.array_equal(f.image, full[round(f.t_ms, 3)]), f.t_ms
