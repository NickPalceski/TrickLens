"""Measurements → subscores → steeze score (step 6c-3).

Pure Python, no CV imports: the API image can import it, and 6d reruns it
over the measurements stored in `analyses.details` once hand-judged clips
exist, without re-running any video.

Each subscore is a clamped linear ramp between two (measurement, score)
points. Where a subscore reads two measurements, it's their mean. A
subscore whose measurement is None is n/a for that trick (measure.py says
when). A clip's breakdown averages each subscore over its *landed* tricks,
skipping the ones where it's n/a, and its steeze score is the mean of the
breakdown's non-null subscores.

**Every constant is a guess** (hence `steeze-v0-uncalibrated`), anchored
on one landed clip: the tripod kickflip, which its skater calls sketchy,
so it should land mid-range rather than near 100. See
docs/components/analyzer.md, Subscores, as built (6c-3). 6d tunes these
constants with `make calibrate` (calibrate.py) against hand-judged clips.
"""

from collections.abc import Mapping, Sequence
from typing import Any

MODEL_VERSION = "steeze-v0-uncalibrated"

SUBSCORES = ("pop", "landing_stability", "roll_away", "stomp", "compactness", "catch")

# (measurement at score_a, score_a, measurement at score_b, score_b)
POP_HEIGHT = (0.08, 20.0, 0.50, 100.0)  # skater heights; 0.08 is Stage A's MIN_POP
SETTLE_MS = (100.0, 100.0, 600.0, 20.0)
TORSO_SWAY_DEG = (2.0, 100.0, 15.0, 20.0)
# Arms windmilling for balance after landing: the kickflip's sketchiness
# (0.62). Its hips settled within 50ms and its torso barely swayed.
ARM_FLAIL = (0.2, 100.0, 0.8, 20.0)  # p90-p10 of arm_ratio over 0.1-0.6s
ROLLAWAY_ON_BOARD = (0.5, 20.0, 1.0, 100.0)
FOOT_DOWN_CAP = 40.0  # roll-away can't score above this with a foot down
STOMP_ERROR = (0.0, 100.0, 0.25, 20.0)  # board lengths off the bolt line
LEG_RATIO = (1.0, 100.0, 1.6, 30.0)  # hip-ankle per torso length: tucked → straight
ARM_RATIO = (1.2, 100.0, 2.2, 40.0)  # farther wrist from the hips per torso length
CATCH_FRAC = (0.0, 30.0, 0.7, 100.0)  # of the airtime, caught before touch-down

Ramp = tuple[float, float, float, float]

# Which measurements each subscore reads, and the ramp each goes through
# (by constant name, so calibrate.py can propose new values for it). A
# subscore with several is their mean.
COMPONENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "pop": (("pop_height", "POP_HEIGHT"),),
    "landing_stability": (
        ("settle_ms", "SETTLE_MS"),
        ("torso_sway_deg", "TORSO_SWAY_DEG"),
        ("arm_flail", "ARM_FLAIL"),
    ),
    "roll_away": (("rollaway_on_board_frac", "ROLLAWAY_ON_BOARD"),),
    "stomp": (("stomp_error", "STOMP_ERROR"),),
    "compactness": (("leg_ratio", "LEG_RATIO"), ("arm_ratio", "ARM_RATIO")),
    "catch": (("catch_frac", "CATCH_FRAC"),),
}


def current_ramps() -> dict[str, Ramp]:
    """Every ramp constant by name, as this module defines it."""
    return {name: globals()[name] for comps in COMPONENTS.values() for _, name in comps}


def ramp(x: float, ramp_def: Ramp) -> float:
    xa, sa, xb, sb = ramp_def
    w = min(1.0, max(0.0, (x - xa) / (xb - xa)))
    return sa + (sb - sa) * w


def _mean(values: Sequence[float | None]) -> float | None:
    vs = [v for v in values if v is not None]
    return sum(vs) / len(vs) if vs else None


def subscores(m: Mapping[str, Any], ramps: Mapping[str, Ramp] | None = None) -> dict:
    """0-100 per subscore (None = n/a) from one trick's measure.measure().
    `ramps` overrides constants by name (calibrate.py tries proposals with
    it); anything not in it comes from this module."""
    use = current_ramps() | dict(ramps or {})
    out: dict[str, float | None] = {}
    for name, comps in COMPONENTS.items():
        parts = [
            None if m.get(key) is None else ramp(float(m[key]), use[ramp_name])
            for key, ramp_name in comps
        ]
        out[name] = _mean(parts)
    if out["roll_away"] is not None and m.get("foot_down"):
        out["roll_away"] = min(out["roll_away"], FOOT_DOWN_CAP)
    return {k: None if v is None else round(v, 1) for k, v in out.items()}


def aggregate(
    per_trick: Sequence[Mapping[str, float | None]],
) -> tuple[dict[str, float | None], float | None]:
    """(breakdown, steeze_score) over the landed tricks' subscores. Every
    subscore is in the breakdown, null where it was n/a on every trick."""
    breakdown = {}
    for name in SUBSCORES:
        v = _mean([t.get(name) for t in per_trick])
        breakdown[name] = None if v is None else round(v, 1)
    steeze = _mean(list(breakdown.values()))
    return breakdown, None if steeze is None else round(steeze, 1)
