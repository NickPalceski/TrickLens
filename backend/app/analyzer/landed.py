"""Did the skater land the trick? (step 6c-2)

Reads one TrickObservation (stage_b.py) over the span just after
touch-down, 0.1-0.6s, when a landed trick has both feet on a board that
rolls on with the skater and a bail has the feet anywhere else. Per
board-sampled frame in that span, the skater is **on the board** when:
- the board box is a plausible board, at most MAX_BOARD_LEN skater-heights
  long. In the bail, the detector sometimes boxed the board together with
  something beside it (0.71 skater-heights wide), and both feet fit inside
  that box;
- both feet (the mean x of each foot's ankle, heel and toe) are within the
  board's x-span, give or take FOOT_MARGIN;
- each foot's lowest point is within FOOT_TO_DECK of the board's top edge.

Independently of the board, a **stance** wider than MAX_STANCE means the
feet can't both be on a board.

Measured on the real clips (docs/components/analyzer.md, The landed check, as
built (6c-2)):

| Clip | On the board (judged / sampled) | Implausible boxes | Stance |
|---|---|---|---|
| Tripod kickflip (landed) | 16/16 of 16 | 0 | 0.26 |
| Follow-cam bail | 2/13 of 16 | 3 | 0.54 |

"Board moving along with the skater" was in the plan too. It's kept as a
measurement only (`board_offset_range`, 0.05 vs 0.27 on these clips) until
more footage shows whether it survives camera motion.

All thresholds are fractions of the skater's standing height, and they're
uncalibrated guesses from two clips.
"""

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np

from app.analyzer import pose as P
from app.analyzer.detect import Detection
from app.analyzer.reasons import CLIP_ENDS, NO_LANDING
from app.analyzer.stage_b import MIN_FOOT_VISIBILITY, TrickObservation

LANDING_FROM_MS = 100  # after touch-down: skip the impact frames themselves
LANDING_TO_MS = 600
# Less footage than this after touch-down and there's nothing to judge:
# "clip ends too soon after the landing".
MIN_FOLLOWUP_MS = 400

MAX_BOARD_LEN = 0.6  # a board is ~0.45-0.5 of a standing skater side-on
FOOT_MARGIN = 0.05
FOOT_TO_DECK = 0.15
MAX_STANCE = 0.45  # landed 0.27, bail 0.55

LANDED_FRAC = 0.7  # of the judged frames
BAILED_FRAC = 0.3
MIN_JUDGED_FRAC = 0.5  # of the board-sampled frames in the span

LEFT = (P.L_ANKLE, P.L_HEEL, P.L_TOE)
RIGHT = (P.R_ANKLE, P.R_HEEL, P.R_TOE)


class Verdict(StrEnum):
    LANDED = "landed"
    BAILED = "bailed"
    UNCLEAR = "unclear"


@dataclass
class LandingCheck:
    verdict: Verdict
    unclear_reason: str | None  # set only when UNCLEAR
    touchdown_ms: float  # Stage B's, or Stage A's landing as a fallback
    sampled: int = 0  # board-sampled frames in the span
    judged: int = 0  # ...with a plausible board and both feet seen
    on_board: int = 0
    implausible_boards: int = 0
    stance: float | None = None  # median, skater heights
    board_offset_range: float | None = None  # measurement only, see module doc
    rows: dict[int, bool] = field(default_factory=dict)  # judged frame row -> on board

    @property
    def on_board_frac(self) -> float:
        return self.on_board / self.judged if self.judged else 0.0

    @property
    def judged_frac(self) -> float:
        return self.judged / self.sampled if self.sampled else 0.0


def foot(pose: P.PoseTrack, row: int, points: tuple[int, ...]) -> tuple[float, float] | None:
    """(centre x, lowest y) of one foot from its confidently-seen points."""
    pts = pose.image[row, list(points)]
    seen = pts[pts[:, 2] >= MIN_FOOT_VISIBILITY]
    if not len(seen) or np.isnan(seen[:, :2]).any():
        return None
    return float(seen[:, 0].mean()), float(seen[:, 1].max())


def plausible(b: Detection, h: float) -> bool:
    """A box short enough to be one board (see MAX_BOARD_LEN)."""
    return b.width <= MAX_BOARD_LEN * h


def feet_on(b: Detection, left: tuple[float, float], right: tuple[float, float], h: float) -> bool:
    """Both feet over the board's x-span and down on its deck. Also used by
    measure.py (6c-3) for roll-away and the catch."""
    m = FOOT_MARGIN * h
    over = all(b.x1 - m <= f[0] <= b.x2 + m for f in (left, right))
    on_deck = all(abs(f[1] - b.y1) <= FOOT_TO_DECK * h for f in (left, right))
    return over and on_deck


def check_landing(obs: TrickObservation, clip_end_ms: float) -> LandingCheck:
    # Stage B's touch-down is the precise one. When it couldn't refine one
    # (feet never clearly left the baseline), Stage A did find a landing.
    td = obs.touchdown_ms if obs.touchdown_ms is not None else obs.window.land_ms
    if min(clip_end_ms, obs.window.end_ms) - td < MIN_FOLLOWUP_MS:
        return LandingCheck(Verdict.UNCLEAR, CLIP_ENDS, td)
    h = obs.skater_h
    if not h > 0:
        return LandingCheck(Verdict.UNCLEAR, NO_LANDING, td)
    lo, hi = td + LANDING_FROM_MS, td + LANDING_TO_MS
    c = LandingCheck(Verdict.UNCLEAR, NO_LANDING, td)

    stances, offsets = [], []
    for row, t in enumerate(obs.pose.t_ms):
        if not lo <= t <= hi:
            continue
        left, right = foot(obs.pose, row, LEFT), foot(obs.pose, row, RIGHT)
        if left and right:
            stances.append(abs(left[0] - right[0]) / h)
        if row not in obs.board:
            continue
        c.sampled += 1
        b = obs.board[row]
        if b is None:
            continue
        if not plausible(b, h):
            c.implausible_boards += 1
            continue
        if not (left and right):
            continue
        c.judged += 1
        c.rows[row] = feet_on(b, left, right, h)
        c.on_board += c.rows[row]
        offsets.append((b.center[0] - (left[0] + right[0]) / 2) / h)

    if stances:
        c.stance = float(np.median(stances))
    if offsets:
        c.board_offset_range = float(np.ptp(offsets))

    if c.stance is not None and c.stance > MAX_STANCE:
        c.verdict, c.unclear_reason = Verdict.BAILED, None
    elif c.judged_frac < MIN_JUDGED_FRAC:
        pass  # UNCLEAR: too little evidence either way
    elif c.on_board_frac >= LANDED_FRAC:
        c.verdict, c.unclear_reason = Verdict.LANDED, None
    elif c.on_board_frac <= BAILED_FRAC:
        c.verdict, c.unclear_reason = Verdict.BAILED, None
    return c
