"""Raw per-trick measurements (step 6c-3).

Reads one judged trick (a TrickObservation from stage_b.py plus its
touch-down) and returns the raw numbers its subscores come from, in
skater heights, milliseconds, degrees or body ratios. No scores here:
calibration.py turns these into 0-100 subscores. The worker stores the
measurements in `analyses.details`, so 6d can recalibrate without
re-running video.

Per subscore, the measurements, and when they're n/a (None):
- **Pop**: `pop_height`, the lowest foot's peak above its resting level in
  the air (60fps pose; Stage A's 15fps peak as a fallback). Never n/a.
- **Landing stability**, over 0-0.6s after touch-down: `settle_ms`, how
  long the hips (height above the lowest foot) take to stay within
  SETTLE_BAND of their riding level; `torso_sway_deg`, the signed torso
  lean's std; `arm_flail`, how far the arms swing (p90-p10 of
  `arm_ratio`). n/a with too little pose.
- **Roll-away**, over 0.6-1.2s after touch-down: `rollaway_on_board_frac`
  and `foot_down`. n/a with under MIN_ROLLAWAY_MS of footage or too few
  judged frames.
- **Stomp**, over the first 0.2s: `foot_pos_lo` / `foot_pos_hi`, each foot
  along the board (0 = one end, 1 = the other), and `stomp_error`, the
  worse foot's distance to its bolt line. n/a when the board is seen
  end-on (`board_len` under MIN_STOMP_BOARD_LEN).
- **Compactness**, median over the air, from the world landmarks:
  `leg_ratio` (hip to ankle) and `arm_ratio` (hips to the farther wrist),
  per torso length. n/a with too little pose in the air.
- **Catch**: `catch_ms` / `catch_frac`, how long before touch-down both
  feet were back on the board, skipping partial board boxes
  (PARTIAL_BOARD). n/a when the feet never left the board (an ollie).

Measured on the tripod kickflip before choosing these (docs/components/
analyzer.md, Subscores, as built (6c-3)). Board-box geometry is only
trusted where it's simple: the box *top* is the nose while the board is
tilted at the pop, so the catch looks at feet leaving the box's x-span
and the stance widening (the flick), not at the gap to the box top.

Every constant here is an uncalibrated guess from one landed clip.
"""

from math import atan2, degrees

import numpy as np

from app.analyzer import landed as L
from app.analyzer import pose as P
from app.analyzer.stage_b import BASELINE_MARGIN_MS, TrickObservation, lowest_foot_y

# Landing stability, over 0-0.6s after touch-down.
STABILITY_TO_MS = 600
SWAY_FROM_MS = 100  # skip the impact frames, as the landed check does
SETTLE_LEVEL_FROM_MS = 400  # riding level: median over 0.4-0.6s
SETTLE_BAND = 0.03  # skater heights. Kickflip: hips within it ~250ms after
MIN_STABILITY_FRAMES = 10

# Roll-away, over 0.6-1.2s after touch-down (after the landed check).
ROLLAWAY_FROM_MS = 600
ROLLAWAY_TO_MS = 1200
MIN_ROLLAWAY_MS = 300
MIN_ROLLAWAY_JUDGED = 3

# Stomp, over the first 0.2s after touch-down.
STOMP_TO_MS = 200
# Bolt lines as a fraction of board length: a 32" deck with a 14" wheelbase
# has its trucks at 9" from each end.
BOLTS = (0.28, 0.72)
# Side-on a board is ~0.45-0.5 skater heights long; shorter than this it's
# seen end-on and positions along it mean little.
MIN_STOMP_BOARD_LEN = 0.3
MIN_STOMP_SAMPLES = 2

# Catch: the feet left the board in the air if a foot left its x-span, or
# the stance widened by this much over the pre-pop stance (kickflip:
# 0.29 -> 0.50).
SEPARATION_STANCE = 0.12
# A board box shorter than this fraction of the trick's median box is a
# partial detection (the 6c-3 prod check: 0.23 skater heights against ~0.5,
# one sample before touch-down), so the sample is skipped like a missing
# board instead of reading as both feet off. A kickflip turns the board
# about its long axis, so its length doesn't really shrink like that.
PARTIAL_BOARD = 0.6

MIN_AIR_POSE_FRAMES = 3


def _rows(obs: TrickObservation, lo: float, hi: float) -> np.ndarray:
    t = obs.pose.t_ms
    return np.flatnonzero((t >= lo) & (t <= hi))


def _r(v: float | None, nd: int = 4) -> float | None:
    if v is None or not np.isfinite(v):
        return None
    return round(float(v), nd)


def air_span(obs: TrickObservation) -> tuple[float, float]:
    """Take-off to touch-down: Stage B's, else Stage A's pop and landing."""
    t0 = obs.takeoff_ms if obs.takeoff_ms is not None else obs.window.pop_ms
    t1 = obs.touchdown_ms if obs.touchdown_ms is not None else obs.window.land_ms
    return t0, t1


def _feet(obs: TrickObservation, row: int):
    return L.foot(obs.pose, row, L.LEFT), L.foot(obs.pose, row, L.RIGHT)


def _torso_deg(w: np.ndarray) -> float:
    """Signed torso lean from vertical in the image plane, from world
    landmarks (x right, y down). Signed, so swaying forward and back
    spreads out; side-on, that's the axis that matters. Depth (z) is left
    out: it's MediaPipe's noisiest axis."""
    v = (w[P.L_SHOULDER] + w[P.R_SHOULDER]) / 2 - (w[P.L_HIP] + w[P.R_HIP]) / 2
    return degrees(atan2(v[0], -v[1]))


def _ratios(w: np.ndarray) -> tuple[float, float]:
    """(arm_ratio, leg_ratio) of one frame's world landmarks."""
    hip = (w[P.L_HIP] + w[P.R_HIP]) / 2
    torso = np.linalg.norm((w[P.L_SHOULDER] + w[P.R_SHOULDER]) / 2 - hip)
    arm = max(np.linalg.norm(w[P.L_WRIST] - hip), np.linalg.norm(w[P.R_WRIST] - hip))
    leg = np.mean(
        [np.linalg.norm(w[P.L_ANKLE] - w[P.L_HIP]), np.linalg.norm(w[P.R_ANKLE] - w[P.R_HIP])]
    )
    return float(arm / torso), float(leg / torso)


def _pop(obs: TrickObservation, t0: float, t1: float) -> dict:
    e = obs.feet_elev[_rows(obs, t0, t1)]
    e = e[np.isfinite(e)]
    height = float(e.max()) if len(e) else obs.window.peak_elevation
    return {
        "pop_height": _r(height),
        "airtime_ms": _r(t1 - t0, 1),
        "stage_a_peak": _r(obs.window.peak_elevation),
    }


def _stability(obs: TrickObservation, td: float) -> dict:
    out = {"settle_ms": None, "absorb_depth": None, "torso_sway_deg": None, "arm_flail": None}
    h = obs.skater_h
    hip_y = (obs.pose.image[:, P.L_HIP, 1] + obs.pose.image[:, P.R_HIP, 1]) / 2
    hh = (lowest_foot_y(obs.pose) - hip_y) / h  # hip height above the lowest foot
    rows = _rows(obs, td, td + STABILITY_TO_MS)
    level_rows = _rows(obs, td + SETTLE_LEVEL_FROM_MS, td + STABILITY_TO_MS)
    if np.isfinite(hh[rows]).sum() >= MIN_STABILITY_FRAMES and np.isfinite(hh[level_rows]).sum():
        level = float(np.nanmedian(hh[level_rows]))
        off = np.abs(hh[rows] - level) > SETTLE_BAND  # NaN compares False: no evidence
        t = obs.pose.t_ms[rows]
        out["settle_ms"] = _r(t[np.flatnonzero(off)[-1]] - td, 1) if off.any() else 0.0
        out["absorb_depth"] = _r(level - np.nanmin(hh[rows]))
    sway = [r for r in _rows(obs, td + SWAY_FROM_MS, td + STABILITY_TO_MS) if obs.pose.found[r]]
    if len(sway) >= MIN_STABILITY_FRAMES:
        out["torso_sway_deg"] = _r(np.std([_torso_deg(obs.pose.world[r]) for r in sway]), 2)
        arms = [_ratios(obs.pose.world[r])[0] for r in sway]
        out["arm_flail"] = _r(np.percentile(arms, 90) - np.percentile(arms, 10))
    return out


def _rollaway(obs: TrickObservation, td: float, clip_end_ms: float) -> dict:
    h = obs.skater_h
    lo = td + ROLLAWAY_FROM_MS
    hi = min(td + ROLLAWAY_TO_MS, clip_end_ms, obs.window.end_ms)
    span = max(0.0, hi - lo)
    on: list[bool] = []
    wide_run = wide_max = 0
    for row in _rows(obs, lo, hi):
        left, right = _feet(obs, row)
        if left and right:
            wide_run = wide_run + 1 if abs(left[0] - right[0]) / h > L.MAX_STANCE else 0
            wide_max = max(wide_max, wide_run)
        b = obs.board.get(row)
        if b is not None and L.plausible(b, h) and left and right:
            on.append(L.feet_on(b, left, right, h))
    out = {"rollaway_ms": _r(span, 1), "rollaway_judged": len(on)}
    if span < MIN_ROLLAWAY_MS or len(on) < MIN_ROLLAWAY_JUDGED:
        return out | {"rollaway_on_board_frac": None, "foot_down": None}
    # A foot down: two judged samples in a row off the board, or the stance
    # too wide for a board for two frames in a row.
    off_twice = any(not a and not b for a, b in zip(on, on[1:], strict=False))
    return out | {
        "rollaway_on_board_frac": _r(sum(on) / len(on)),
        "foot_down": bool(off_twice or wide_max >= 2),
    }


def _stomp(obs: TrickObservation, td: float) -> dict:
    h = obs.skater_h
    lo_pos, hi_pos, lens = [], [], []
    for row in _rows(obs, td, td + STOMP_TO_MS):
        b = obs.board.get(row)
        left, right = _feet(obs, row)
        if b is None or not L.plausible(b, h) or not (left and right) or b.width <= 0:
            continue
        a, c = sorted((f[0] - b.x1) / b.width for f in (left, right))
        lo_pos.append(a)
        hi_pos.append(c)
        lens.append(b.width / h)
    out = {"board_len": None, "foot_pos_lo": None, "foot_pos_hi": None, "stomp_error": None}
    if len(lens) < MIN_STOMP_SAMPLES:
        return out
    lo, hi, blen = (float(np.median(v)) for v in (lo_pos, hi_pos, lens))
    out |= {"board_len": _r(blen), "foot_pos_lo": _r(lo), "foot_pos_hi": _r(hi)}
    if blen >= MIN_STOMP_BOARD_LEN:
        out["stomp_error"] = _r(max(abs(lo - BOLTS[0]), abs(hi - BOLTS[1])))
    return out


def _compactness(obs: TrickObservation, t0: float, t1: float) -> dict:
    rows = [r for r in _rows(obs, t0, t1) if obs.pose.found[r]]
    if len(rows) < MIN_AIR_POSE_FRAMES:
        return {"arm_ratio": None, "leg_ratio": None}
    arm, leg = zip(*(_ratios(obs.pose.world[r]) for r in rows), strict=True)
    return {"arm_ratio": _r(np.median(arm)), "leg_ratio": _r(np.median(leg))}


def _catch(obs: TrickObservation, t0: float, t1: float) -> dict:
    h = obs.skater_h
    stance = lambda lr: abs(lr[0][0] - lr[1][0]) / h  # noqa: E731
    pre = [
        stance(f)
        for r in _rows(obs, obs.window.start_ms, t0 - BASELINE_MARGIN_MS)
        if all(f := _feet(obs, r))
    ]
    air = [stance(f) for r in _rows(obs, t0, t1) if all(f := _feet(obs, r))]
    spread = max(air) - float(np.median(pre)) if pre and air else None

    samples = []
    for row in _rows(obs, t0, t1):
        b = obs.board.get(row)
        left, right = _feet(obs, row)
        if b is not None and L.plausible(b, h) and left and right:
            samples.append((float(obs.pose.t_ms[row]), b, left, right))
    typical = float(np.median([b.width for _, b, _, _ in samples])) if samples else 0.0
    whole = [x for x in samples if x[1].width >= PARTIAL_BOARD * typical]

    judged: list[tuple[float, bool]] = []  # (t, both feet on the board)
    left_span = False
    m = L.FOOT_MARGIN * h
    for t, b, left, right in whole:
        left_span |= any(not b.x1 - m <= f[0] <= b.x2 + m for f in (left, right))
        judged.append((t, L.feet_on(b, left, right, h)))
    separated = left_span or (spread is not None and spread >= SEPARATION_STANCE)
    out = {
        "separated": separated,
        "air_stance_spread": _r(spread),
        "partial_boards": len(samples) - len(whole),
    }
    if not separated:
        return out | {"catch_ms": None, "catch_frac": None}
    # The last run of on-board samples before touch-down; caught at
    # touch-down itself if the last judged sample was still off.
    caught = t1
    for t, on in reversed(judged):
        if not on:
            break
        caught = t
    return out | {
        "catch_ms": _r(t1 - caught, 1),
        "catch_frac": _r((t1 - caught) / (t1 - t0)) if t1 > t0 else None,
    }


def measure(obs: TrickObservation, touchdown_ms: float, clip_end_ms: float) -> dict:
    """Every raw measurement for one trick, JSON-ready (floats, bools, None).
    `touchdown_ms` is the landed check's (Stage B's, else Stage A's)."""
    t0, t1 = air_span(obs)
    return (
        _pop(obs, t0, t1)
        | _stability(obs, touchdown_ms)
        | _rollaway(obs, touchdown_ms, clip_end_ms)
        | _stomp(obs, touchdown_ms)
        | _compactness(obs, t0, t1)
        | _catch(obs, t0, t1)
    )
