"""Stage B: look closely at one trick window (step 6c).

Stage A (localize.py) found each pop at 15fps. Stage B decodes just that
trick's ~1.2s window at the clip's native rate (60fps for phone footage)
and, in one pass:
- runs **pose** on every frame (pose.py);
- runs the **board** detector on every other frame around the pop and the
  landing, with the same full-frame + zoomed-crop merge as Stage A. Stage
  A's 15fps board box was visibly stale at the moment of landing;
- refines **take-off** and **touch-down** from the feet at full frame rate.
  On the tripod kickflip, Stage A's landing (1.57s) is ~80ms before the
  feet actually reach the board.

6c-1 stops at these observations: the worker logs them, nothing is stored
and nothing is scored yet. 6c-2 (landed check, confidence gate) and 6c-3
(measurements, scores) build on TrickObservation.
"""

import time
from dataclasses import dataclass, field

import numpy as np

from app.analyzer import pose as P
from app.analyzer.detect import SKATEBOARD, Detection, get_detector
from app.analyzer.frames import iter_frames
from app.analyzer.localize import SAMPLE_FPS, StageAResult, TrickWindow, board_crop, board_near
from app.analyzer.media import VideoInfo
from app.analyzer.track import iou

# Board detection every BOARD_EVERY-th frame (30fps at 60fps source), over
# [pop - BOARD_BEFORE_MS, land + BOARD_AFTER_MS]: the air and the ~0.6s
# after landing that the landed check (6c-2) reads.
BOARD_EVERY = 2
BOARD_BEFORE_MS = 200
BOARD_AFTER_MS = 700

# Feet count as "off" whatever they stand on once the lowest foot point is
# this many skater-heights above its on-board/on-ground baseline. Pose
# jitter on the feet is ~1-2% of skater height on the real clips.
FEET_OFF = 0.04
# Baseline frames: before Stage A's pop and after its landing, by this margin.
BASELINE_MARGIN_MS = 120
MIN_FOOT_VISIBILITY = 0.5


@dataclass
class TrickObservation:
    window: TrickWindow
    fps: float
    pose: P.PoseTrack
    skater: list[Detection | None]  # per frame (interpolated from Stage A)
    board: dict[int, Detection | None]  # frame row -> board, sampled frames only
    skater_h: float  # standing height, px (Stage A rolling median over the window)
    feet_elev: np.ndarray  # (N,) lowest foot above its baseline, in skater heights
    takeoff_ms: float | None  # first frame with both feet off; None if not refined
    touchdown_ms: float | None  # first frame back down
    timings_s: dict[str, float] = field(default_factory=dict)

    @property
    def board_found_frac(self) -> float:
        return sum(b is not None for b in self.board.values()) / max(1, len(self.board))


def _interp_box(a: Detection, b: Detection, w: float) -> Detection:
    lerp = lambda u, v: u + (v - u) * w  # noqa: E731
    return Detection(
        a.cls, a.score, lerp(a.x1, b.x1), lerp(a.y1, b.y1), lerp(a.x2, b.x2), lerp(a.y2, b.y2)
    )


def skater_at(stage_a: StageAResult, t_ms: float) -> Detection | None:
    """The skater's box at any time, linearly between Stage A's 15fps samples."""
    pos = t_ms * SAMPLE_FPS / 1000.0
    i0 = int(np.floor(pos))
    if i0 < 0 or i0 >= len(stage_a.skater):
        return None
    a = stage_a.skater[i0]
    b = stage_a.skater[i0 + 1] if i0 + 1 < len(stage_a.skater) else None
    if a is None:
        return b if b is not None and pos - i0 > 0.5 else None
    return _interp_box(a, b, pos - i0) if b is not None else a


def lowest_foot_y(pose: P.PoseTrack) -> np.ndarray:
    """Per frame, the y (px) of the lowest confidently-seen foot point."""
    feet = pose.image[:, P.FEET, :]
    y = np.where(feet[:, :, 2] >= MIN_FOOT_VISIBILITY, feet[:, :, 1], np.nan)
    out = np.full(len(y), np.nan)
    seen = ~np.all(np.isnan(y), axis=1)  # nanmax warns on all-NaN rows
    out[seen] = np.nanmax(y[seen], axis=1)
    return out


def refine_contacts(
    t_ms: np.ndarray, feet_y: np.ndarray, skater_h: float, window: TrickWindow
) -> tuple[np.ndarray, float | None, float | None]:
    """Feet elevation and the refined take-off / touch-down times.

    The baseline is wherever the lowest foot rests: on the deck before the
    pop, and on the deck *or* the ground after (a bail lands on the ground).
    Each side is a median, joined by a straight line across the trick, which
    also absorbs slow camera drift within the window. Elevation is in
    skater heights. Take-off is the first frame of the airborne run around
    the highest point, and touch-down is the first frame after it.
    """
    nan = np.full(len(t_ms), np.nan)
    pre = (t_ms < window.pop_ms - BASELINE_MARGIN_MS) & ~np.isnan(feet_y)
    post = (t_ms > window.land_ms + BASELINE_MARGIN_MS) & ~np.isnan(feet_y)
    if not pre.any() and not post.any():
        return nan, None, None
    if pre.any() and post.any():
        t0, y0 = np.median(t_ms[pre]), np.median(feet_y[pre])
        t1, y1 = np.median(t_ms[post]), np.median(feet_y[post])
        base = y0 + (y1 - y0) * (t_ms - t0) / (t1 - t0)
    else:
        base = np.full(len(t_ms), np.median(feet_y[pre if pre.any() else post]))
    elev = (base - feet_y) / skater_h

    span = (t_ms >= window.pop_ms - 100) & (t_ms <= window.land_ms + 100) & ~np.isnan(elev)
    if not span.any():
        return elev, None, None
    apex = int(np.flatnonzero(span)[np.nanargmax(np.where(span, elev, -np.inf)[span])])
    if not elev[apex] >= FEET_OFF:
        return elev, None, None
    a = apex
    while a > 0 and not (elev[a - 1] < FEET_OFF):  # NaN (missed pose) doesn't end the run
        a -= 1
    b = apex
    while b < len(elev) - 1 and not (elev[b + 1] < FEET_OFF):
        b += 1
    takeoff = float(t_ms[a]) if a > 0 else None
    touchdown = float(t_ms[b + 1]) if b + 1 < len(elev) else None
    return elev, takeoff, touchdown


def observe(
    path: str,
    info: VideoInfo,
    stage_a: StageAResult,
    window: TrickWindow,
    yolox_path: str,
    pose_path: str,
) -> TrickObservation:
    """Stage B for one window of a processed clip."""
    timings: dict[str, float] = {}
    fps = float(info.output_fps)
    detector = get_detector(yolox_path)
    w, h = info.width, info.height

    hs = [
        s.height
        for i, s in enumerate(stage_a.skater)
        if s is not None and window.start_ms <= i * 1000 / SAMPLE_FPS <= window.end_ms
    ]
    skater_h = float(np.median(hs)) if hs else float("nan")

    board_lo, board_hi = window.pop_ms - BOARD_BEFORE_MS, window.land_ms + BOARD_AFTER_MS
    skater: list[Detection | None] = []
    board: dict[int, Detection | None] = {}
    t_board = 0.0

    def frames():
        nonlocal t_board
        for row, f in enumerate(iter_frames(path, w, h, fps, window.start_ms, window.end_ms)):
            s = skater_at(stage_a, f.t_ms)
            skater.append(s)
            if s is not None and board_lo <= f.t_ms <= board_hi and row % BOARD_EVERY == 0:
                t0 = time.perf_counter()
                full = [d for d in detector.detect(f.image) if d.cls == SKATEBOARD]
                x1, y1, x2, y2 = board_crop(s, w, h)
                crop = [
                    d.offset(x1, y1)
                    for d in detector.detect(f.image[y1:y2, x1:x2], classes=(SKATEBOARD,))
                ]
                merged = full + [c for c in crop if all(iou(c, b) <= 0.5 for b in full)]
                board[row] = board_near(merged, s)
                t_board += time.perf_counter() - t0
            yield f

    t0 = time.perf_counter()
    pose = P.run_pose(frames(), w, h, pose_path)
    timings["pose_and_board"] = time.perf_counter() - t0
    timings["board"] = t_board

    t0 = time.perf_counter()
    elev, takeoff, touchdown = refine_contacts(pose.t_ms, lowest_foot_y(pose), skater_h, window)
    timings["refine"] = time.perf_counter() - t0
    return TrickObservation(
        window=window,
        fps=fps,
        pose=pose,
        skater=skater,
        board=board,
        skater_h=skater_h,
        feet_elev=elev,
        takeoff_ms=takeoff,
        touchdown_ms=touchdown,
        timings_s=timings,
    )
