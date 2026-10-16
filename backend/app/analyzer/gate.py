"""The confidence gate (step 6c-2): which tricks count, and does the clip
get a score at all?

Fail safe: a clip the analyzer can't judge well becomes `unanalyzable`
with a *specific* reason (reasons.py), never a guess. Per trick, in order:
1. the skater is missing from too much of the trick → "trick left the frame";
2. pose can't follow them → "body not clearly visible";
3. the landed check (landed.py) → landed, bailed, or unclear.

Landed tricks are the ones that get scored (6c-3), averaged. Bails and
unclear tricks are left out, not zeroed. The clip only fails when no trick
was landed. Then the reason is the most actionable one among its tricks
(TRICK_PRIORITY), so a user whose only trick left the frame hears that,
not "no landed trick detected".

A trick whose analysis crashed (6c-3) arrives as None and is left out
like a bail, as "analysis failed for this trick". If nothing else landed,
the clip fails as "analysis failed": the crashed trick may have been the
landed one, so "no landed trick detected" could be wrong.

Clip-level checks come first: no pops at all → "no clean airtime found";
a skater too small in frame → "skater too far from camera". "Too dark" is
an *explanation* only. A dark clip that still tracks fine gets scored;
when a dark clip fails, "too dark" replaces the reason, because darkness is
the likely cause and the fix.

`confidence` summarises the same evidence as one number in [0, 1]: each
factor maps its gate threshold to 0.5 and a "clearly good" level to 1.0,
and a trick's confidence is its weakest factor. The checks above decide
pass/fail; the number is for the analyses row and the UI.

Every threshold is an uncalibrated guess from two real clips (both pass
every check by a wide margin), to revisit as clips come in.
"""

from dataclasses import dataclass

import numpy as np

from app.analyzer import landed as L
from app.analyzer.localize import StageAResult
from app.analyzer.reasons import (
    ANALYSIS_FAILED,
    BODY_NOT_VISIBLE,
    CLIP_ENDS,
    LEFT_FRAME,
    NO_AIRTIME,
    NO_LANDING,
    TOO_DARK,
    TOO_FAR,
    TRICK_FAILED,
)
from app.analyzer.stage_b import TrickObservation

MIN_BRIGHTNESS = 40.0  # mean luma, 0-255. No dark test clip yet
MIN_SKATER_HEIGHT = 0.08  # of frame height. The tripod kickflip is 0.14
GOOD_SKATER_HEIGHT = 0.15
MAX_SKATER_MISSING = 0.3  # of the trick's frames, pop to touch-down + 0.6s
MIN_POSE_FOUND = 0.6  # real clips: 0.92 and 1.0
GOOD_POSE_FOUND = 0.95
MIN_FEET_VISIBILITY = 0.5  # real clips: 0.92 and 0.95
GOOD_FEET_VISIBILITY = 0.9
GOOD_JUDGED_FRAC = 0.9  # landing evidence; the gate's own bar is landed.MIN_JUDGED_FRAC
# Known limits: a board flip lasts ~100ms, so 30fps footage is judged on
# a third of the frames 60fps gets.
GOOD_FPS, MIN_FPS = 50.0, 24.0

TRICK_PRIORITY = (LEFT_FRAME, BODY_NOT_VISIBLE, CLIP_ENDS, NO_LANDING)


def _factor(value: float, threshold: float, good: float) -> float:
    """threshold -> 0.5, good -> 1.0, linear between, clamped to [0, 1]."""
    return float(np.clip(0.5 + 0.5 * (value - threshold) / (good - threshold), 0.0, 1.0))


@dataclass
class TrickAssessment:
    obs: TrickObservation | None  # None: Stage B (or measuring it) crashed
    landing: L.LandingCheck | None  # None when an earlier check failed
    failure: str | None  # why it can't be judged; None when landed or bailed
    confidence: float

    @property
    def outcome(self) -> str:
        """`landed`, `bailed`, or the failure reason."""
        if self.failure is not None:
            return self.failure
        assert self.landing is not None
        return str(self.landing.verdict)


@dataclass
class ClipAssessment:
    tricks: list[TrickAssessment]
    failure_reason: str | None  # None: the landed tricks get scored
    confidence: float

    @property
    def landed(self) -> list[TrickAssessment]:
        return [t for t in self.tricks if t.outcome == L.Verdict.LANDED]


def skater_missing_frac(obs: TrickObservation, until_ms: float) -> float:
    rows = [i for i, t in enumerate(obs.pose.t_ms) if obs.window.pop_ms <= t <= until_ms]
    if not rows:
        return 1.0
    return sum(obs.skater[i] is None for i in rows) / len(rows)


def assess_trick(obs: TrickObservation, clip_end_ms: float, size_factor: float) -> TrickAssessment:
    td = obs.touchdown_ms if obs.touchdown_ms is not None else obs.window.land_ms
    fps_factor = _factor(obs.fps, MIN_FPS, GOOD_FPS)
    factors = [
        size_factor,
        fps_factor,
        _factor(obs.pose.found_frac, MIN_POSE_FOUND, GOOD_POSE_FOUND),
        _factor(obs.pose.feet_visibility(), MIN_FEET_VISIBILITY, GOOD_FEET_VISIBILITY),
    ]
    if skater_missing_frac(obs, td + L.LANDING_TO_MS) > MAX_SKATER_MISSING:
        return TrickAssessment(obs, None, LEFT_FRAME, min(factors))
    if obs.pose.found_frac < MIN_POSE_FOUND or obs.pose.feet_visibility() < MIN_FEET_VISIBILITY:
        return TrickAssessment(obs, None, BODY_NOT_VISIBLE, min(factors))
    landing = L.check_landing(obs, clip_end_ms)
    if landing.sampled:
        factors.append(_factor(landing.judged_frac, L.MIN_JUDGED_FRAC, GOOD_JUDGED_FRAC))
    return TrickAssessment(obs, landing, landing.unclear_reason, min(factors))


def assess_clip(
    stage_a: StageAResult, observations: list[TrickObservation | None], clip_end_ms: float
) -> ClipAssessment:
    """Judge a clip from Stage A and the Stage B observation of each of its
    windows, in order. None stands for a trick whose analysis crashed."""
    dark = stage_a.brightness < MIN_BRIGHTNESS
    too_far = stage_a.skater_height_frac < MIN_SKATER_HEIGHT

    if not stage_a.windows:
        reason = TOO_DARK if dark else TOO_FAR if too_far else NO_AIRTIME
        return ClipAssessment([], reason, 0.0)

    size_factor = _factor(stage_a.skater_height_frac, MIN_SKATER_HEIGHT, GOOD_SKATER_HEIGHT)
    tricks = [
        TrickAssessment(None, None, TRICK_FAILED, 0.0)
        if o is None
        else assess_trick(o, clip_end_ms, size_factor)
        for o in observations
    ]
    confidence = float(np.mean([t.confidence for t in tricks])) if tricks else 0.0
    if too_far:
        return ClipAssessment(tricks, TOO_DARK if dark else TOO_FAR, confidence)

    landed = [t for t in tricks if t.outcome == L.Verdict.LANDED]
    if landed:
        return ClipAssessment(tricks, None, float(np.mean([t.confidence for t in landed])))

    # Nothing landed. A crashed trick might have been the landed one, so
    # the clip can't honestly claim more than that the analysis failed.
    if any(t.failure == TRICK_FAILED for t in tricks):
        return ClipAssessment(tricks, ANALYSIS_FAILED, confidence)
    # Bails and unclear landings both read as "no landed trick detected";
    # any more specific reason wins over that.
    outcomes = {NO_LANDING if t.outcome == L.Verdict.BAILED else t.outcome for t in tricks}
    reason = next((r for r in TRICK_PRIORITY if r in outcomes), NO_LANDING)
    return ClipAssessment(tricks, TOO_DARK if dark else reason, confidence)
