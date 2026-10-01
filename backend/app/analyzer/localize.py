"""Stage A: find the tricks in a clip (step 6b).

Cheap and coarse on purpose. At SAMPLE_FPS, detect the skater and board,
then find **pops**: moments where the board *and* the skater's feet both
leave the ground. Each pop becomes a TrickWindow, the ~1.2s span Stage B
(6c) will analyze at full frame rate with pose. A multi-trick line simply
yields several windows.

Two decisions here came out of measuring the real clips, not the plan:

- **Ground level is estimated locally, not by cancelling camera motion.**
  On the follow-cam clip, motion measured from background features (distant
  trees) made the ground drift *worse* (40px over 1.4s vs 23px raw). The
  background isn't the ground the skater is rolling on, and the skater
  also moves toward or away from the camera. So the ground is a rolling
  high percentile of each signal's own y values (image y grows downward),
  taken over a window wider than any airtime. That absorbs slow camera
  drift and approach/recede without modelling the camera at all.
- **A pop needs the board and the feet to agree.** On the ground the
  board's box bottom jitters by ~0.1 of the skater's height, as much as a
  small pop. The skater box's bottom edge (the lowest foot) is steadier,
  but rises when the skater just jumps. The airborne signal is therefore
  the *minimum* of the two elevations. Noise in one can't fake a pop, a
  carried board can't (feet stay down), and a hop off the board can't
  (board stays down).

Heights are normalized by the skater's own standing height (rolling
median of their box), which makes them camera-distance invariant. That
uses a rolling median, not the per-frame height, because the box grows
mid-trick when the arms go up.
"""

import time
from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks

from app.analyzer.detect import PERSON, SKATEBOARD, Detection, get_detector
from app.analyzer.frames import iter_frames
from app.analyzer.media import VideoInfo
from app.analyzer.track import iou, pick_skater, track_people

SAMPLE_FPS = 15

# --- Detection ---------------------------------------------------------------
# A board counts as "at the skater's feet" within this many skater-heights of
# the bottom-centre of their box. Generous, because mid-flip or mid-bail the
# board is legitimately away from the feet.
BOARD_MAX_DIST = 1.0
# The board-only zoom pass crops a square of this many skater-heights around
# the feet. That upscales a small, distant board ~1.5-2x into the detector's
# input. On the tripod kickflip, full-frame-only found the board in 30/59
# frames, and full frame + this crop found it in 56/59.
CROP_SIDE = 1.4

# --- Signal ------------------------------------------------------------------
MAX_GAP_SAMPLES = 3  # detector misses up to ~0.2s are interpolated over
GROUND_WINDOW_S = 1.5  # wider than any airtime, so ground samples dominate
GROUND_PERCENTILE = 80  # high y = low in the image = on the ground
HEIGHT_WINDOW_S = 2.0

# --- Pop criteria (fractions of the skater's standing height) -----------------
MIN_POP = 0.08  # peak airborne elevation
MIN_BOARD_RISE = 0.06  # the board itself must clear the ground somewhere in the pop
ONSET_FRAC = 0.3  # pop/landing = where elevation crosses this fraction of the peak
MIN_AIRTIME_MS = 130
# A backstop only. The rolling ground estimate adopts any level held longer
# than about half of GROUND_WINDOW_S, so long "airtime" rarely reaches this
# check. Terrain changes (ledges, drops, stair sets) aren't modelled yet.
MAX_AIRTIME_MS = 1500
MIN_POP_SEPARATION_S = 0.6

# --- Window -----------------------------------------------------------------
WINDOW_BEFORE_MS = 400
WINDOW_AFTER_MS = 800  # after the pop; extended to land + WINDOW_AFTER_LAND_MS if longer
WINDOW_AFTER_LAND_MS = 400


@dataclass(frozen=True)
class TrickWindow:
    pop_ms: float  # both board and feet leave the ground
    apex_ms: float  # highest airborne point
    land_ms: float  # back on the ground
    start_ms: float  # analysis window for Stage B
    end_ms: float
    peak_elevation: float  # at apex, in skater heights (min of board and feet)

    @property
    def airtime_ms(self) -> float:
        return self.land_ms - self.pop_ms


@dataclass
class Signals:
    """Per-sample series. NaN where nothing was detected."""

    t_ms: np.ndarray
    feet_y: np.ndarray
    board_y: np.ndarray
    skater_h: np.ndarray
    elev_feet: np.ndarray = field(default_factory=lambda: np.array([]))
    elev_board: np.ndarray = field(default_factory=lambda: np.array([]))
    elev_air: np.ndarray = field(default_factory=lambda: np.array([]))


@dataclass
class StageAResult:
    windows: list[TrickWindow]
    signals: Signals
    skater: list[Detection | None]  # per sample, for the debug video
    board: list[Detection | None]
    others: list[list[Detection]]  # every other person, per sample
    frame_size: tuple[int, int]  # (width, height)
    timings_s: dict[str, float]

    @property
    def skater_coverage(self) -> float:
        """Fraction of samples with the skater in frame."""
        return sum(s is not None for s in self.skater) / max(1, len(self.skater))

    @property
    def skater_height_frac(self) -> float:
        """Median skater height as a fraction of the frame height. 6c's
        'too far from camera' gate reads this. The tripod kickflip is ~0.13."""
        hs = [s.height for s in self.skater if s is not None]
        return float(np.median(hs)) / self.frame_size[1] if hs else 0.0


# --- Pure signal processing (unit-tested without models) ----------------------


def _fill_gaps(x: np.ndarray, max_gap: int) -> np.ndarray:
    """Linearly interpolate interior NaN runs of at most `max_gap` samples."""
    x = x.astype(float).copy()
    n = len(x)
    i = 0
    while i < n:
        if np.isnan(x[i]):
            j = i
            while j < n and np.isnan(x[j]):
                j += 1
            if i > 0 and j < n and (j - i) <= max_gap:
                x[i:j] = np.linspace(x[i - 1], x[j], j - i + 2)[1:-1]
            i = j
        else:
            i += 1
    return x


def _rolling(x: np.ndarray, half: int, fn) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        w = x[max(0, i - half) : i + half + 1]
        w = w[~np.isnan(w)]
        if len(w):
            out[i] = fn(w)
    return out


def compute_elevation(sig: Signals, fps: float = SAMPLE_FPS) -> Signals:
    """Fill sig.elev_* in place (and return it). Elevations are in skater
    heights above the local ground; positive is up."""
    feet = _rolling(_fill_gaps(sig.feet_y, MAX_GAP_SAMPLES), 1, np.median)
    board = _rolling(_fill_gaps(sig.board_y, MAX_GAP_SAMPLES), 1, np.median)
    # The rolling median above would otherwise bleed values into long gaps.
    feet[np.isnan(_fill_gaps(sig.feet_y, MAX_GAP_SAMPLES))] = np.nan
    board[np.isnan(_fill_gaps(sig.board_y, MAX_GAP_SAMPLES))] = np.nan

    g_half = max(1, int(GROUND_WINDOW_S * fps / 2))
    ground_feet = _rolling(feet, g_half, lambda w: np.percentile(w, GROUND_PERCENTILE))
    ground_board = _rolling(board, g_half, lambda w: np.percentile(w, GROUND_PERCENTILE))
    height = _rolling(sig.skater_h, max(1, int(HEIGHT_WINDOW_S * fps / 2)), np.median)

    with np.errstate(invalid="ignore", divide="ignore"):
        sig.elev_feet = (ground_feet - feet) / height
        sig.elev_board = (ground_board - board) / height
    # Both off the ground. Where the board wasn't seen (edge-on mid-flip, a
    # long miss), the feet stand in. find_pops() separately requires board
    # evidence somewhere in each pop.
    sig.elev_air = np.where(
        np.isnan(sig.elev_board), sig.elev_feet, np.fmin(sig.elev_feet, sig.elev_board)
    )
    return sig


def find_pops(sig: Signals, fps: float = SAMPLE_FPS) -> list[TrickWindow]:
    """Pops in an elevation-filled Signals (compute_elevation first)."""
    t = sig.t_ms
    air = np.nan_to_num(sig.elev_air, nan=0.0)
    if len(air) < 3:
        return []
    peaks, _ = find_peaks(
        air,
        height=MIN_POP,
        prominence=MIN_POP * 0.75,
        distance=max(1, int(MIN_POP_SEPARATION_S * fps)),
    )
    duration_ms = t[-1] + 1000.0 / fps
    windows: list[TrickWindow] = []
    for p in peaks:
        level = air[p] * ONSET_FRAC
        a = p
        while a > 0 and air[a - 1] >= level:
            a -= 1
        b = p
        while b < len(air) - 1 and air[b + 1] >= level:
            b += 1
        # The pop/landing instants are the first/last airborne samples'
        # outer edges: halfway to the neighbouring on-ground sample.
        pop_ms = t[a] - 500.0 / fps if a > 0 else t[a]
        land_ms = t[b] + 500.0 / fps if b < len(air) - 1 else t[b]
        airtime = land_ms - pop_ms
        if not MIN_AIRTIME_MS <= airtime <= MAX_AIRTIME_MS:
            continue
        board_seg = sig.elev_board[a : b + 1]
        if not np.any(np.nan_to_num(board_seg, nan=-1.0) >= MIN_BOARD_RISE):
            continue
        windows.append(
            TrickWindow(
                pop_ms=float(pop_ms),
                apex_ms=float(t[p]),
                land_ms=float(land_ms),
                start_ms=float(max(0.0, pop_ms - WINDOW_BEFORE_MS)),
                end_ms=float(
                    min(duration_ms, max(pop_ms + WINDOW_AFTER_MS, land_ms + WINDOW_AFTER_LAND_MS))
                ),
                peak_elevation=float(air[p]),
            )
        )
    return windows


# --- The model-driven part ------------------------------------------------------


def _feet(box: Detection) -> tuple[float, float]:
    return (box.x1 + box.x2) / 2, box.y2


def _board_near(boards: list[Detection], skater: Detection) -> Detection | None:
    fx, fy = _feet(skater)

    def dist(b: Detection) -> float:
        cx, cy = b.center
        return float(np.hypot(cx - fx, cy - fy)) / skater.height

    near = [b for b in boards if dist(b) <= BOARD_MAX_DIST]
    return min(near, key=dist, default=None)


def _crop(skater: Detection, width: int, height: int) -> tuple[int, int, int, int]:
    side = CROP_SIDE * skater.height
    fx, fy = _feet(skater)
    x1, x2 = max(0, int(fx - side / 2)), min(width, int(fx + side / 2))
    # Mostly above the feet (where the board goes in the air), a little below.
    y1, y2 = max(0, int(fy - 0.9 * side)), min(height, int(fy + 0.1 * side))
    return x1, y1, x2, y2


def analyze(path: str, info: VideoInfo, model_path: str) -> StageAResult:
    """Run Stage A on a processed clip (media.py's output, probed as `info`).

    Two decode passes rather than holding frames in memory: 30s of 720p at
    15fps is ~1.2GB of raw frames, and re-decoding takes about a second.
    """
    timings: dict[str, float] = {}
    detector = get_detector(model_path)
    w, h = info.width, info.height

    # Pass 1: full-frame people + boards, every sample.
    t0 = time.perf_counter()
    people: list[list[Detection]] = []
    full_boards: list[list[Detection]] = []
    for f in iter_frames(path, w, h, SAMPLE_FPS):
        dets = detector.detect(f.image)
        people.append([d for d in dets if d.cls == PERSON])
        full_boards.append([d for d in dets if d.cls == SKATEBOARD])
    timings["detect_full"] = time.perf_counter() - t0

    tracks = track_people(people)
    near = {
        (tr.id, i): _board_near(full_boards[i], box) is not None
        for tr in tracks
        for i, box in tr.boxes.items()
    }
    main = pick_skater(tracks, near)
    n = len(people)
    skater: list[Detection | None] = [main.boxes.get(i) if main else None for i in range(n)]
    others = [[p for p in people[i] if skater[i] is None or p is not skater[i]] for i in range(n)]

    # Pass 2: zoomed board-only pass around the skater's feet.
    t0 = time.perf_counter()
    board: list[Detection | None] = [None] * n
    for f in iter_frames(path, w, h, SAMPLE_FPS):
        i = f.index
        if i >= n or skater[i] is None:
            continue
        x1, y1, x2, y2 = _crop(skater[i], w, h)
        crop_boards = [
            d.offset(x1, y1) for d in detector.detect(f.image[y1:y2, x1:x2], classes=(SKATEBOARD,))
        ]
        merged = list(full_boards[i]) + [
            c for c in crop_boards if all(iou(c, b) <= 0.5 for b in full_boards[i])
        ]
        board[i] = _board_near(merged, skater[i])
    timings["detect_crop"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    nan = float("nan")
    sig = Signals(
        t_ms=np.arange(n) * 1000.0 / SAMPLE_FPS,
        feet_y=np.array([s.y2 if s else nan for s in skater], dtype=float),
        # The board's centre, not its bottom edge: on a pop the tail stays near
        # the ground while the nose lifts, so the lowest point barely moves (the
        # follow-cam bail's board bottom rose one sample, ~0.09; its centre rose a
        # steady ~0.12 over four). For a board clearly in the air, centre and
        # bottom rise alike.
        board_y=np.array([b.center[1] if b else nan for b in board], dtype=float),
        skater_h=np.array([s.height if s else nan for s in skater], dtype=float),
    )
    compute_elevation(sig)
    windows = find_pops(sig)
    timings["localize"] = time.perf_counter() - t0
    return StageAResult(windows, sig, skater, board, others, (w, h), timings)
