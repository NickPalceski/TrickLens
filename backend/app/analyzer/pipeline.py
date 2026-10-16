"""The analyzer end to end on one processed clip (step 6c-3).

Stage A (localize.py) → per trick: Stage B (stage_b.py) → the gate
(gate.py, with landed.py) → per judged trick: measurements (measure.py) →
per landed trick: subscores (calibration.py) → the clip's breakdown and
steeze score. app/worker.py and `make analyze-clip` (cli.py) both call
analyze(), so the CLI really does run the worker's path.

**Crashes.** A crash in one trick's Stage B, or in measuring a landed
trick, fails only that trick ("analysis failed for this trick"); the
others are still judged and scored, and gate.py decides what that means
for the clip. A crash anywhere else (Stage A, the gate) propagates, and
the worker marks the whole clip "analysis failed". There's no S3 or
database access in here, so an exception is always the analyzer's or the
clip's, never a transient infrastructure error worth retrying. See
docs/components/analyzer.md, Worker.
"""

import logging
import time
from dataclasses import dataclass, field

import numpy as np

from app.analyzer import calibration, gate, localize, measure, media, stage_b
from app.analyzer.landed import Verdict

log = logging.getLogger("tricklens.analyzer")

DETAILS_SCHEMA = 1


@dataclass
class AnalysisResult:
    info: media.VideoInfo  # of the processed clip
    stage_a: localize.StageAResult
    observations: list[stage_b.TrickObservation | None]  # per window; None = crashed
    verdict: gate.ClipAssessment
    measurements: list[dict | None]  # per window
    subscores: list[dict | None]  # per window, landed tricks only
    breakdown: dict[str, float | None] | None  # None when the clip fails
    steeze_score: float | None
    timings_s: dict[str, float] = field(default_factory=dict)

    @property
    def failure_reason(self) -> str | None:
        return self.verdict.failure_reason

    @property
    def confidence(self) -> float:
        return self.verdict.confidence

    @property
    def thumb_at_ms(self) -> int:
        """The apex of the biggest pop, else the middle of the clip."""
        if self.stage_a.windows:
            return int(max(self.stage_a.windows, key=lambda w: w.peak_elevation).apex_ms)
        return self.info.duration_ms // 2

    def details(self) -> dict:
        """`analyses.details` (docs/components/data-model.md): the evidence
        and raw measurements behind the score, JSON-ready. NaN never gets
        in, since Postgres JSONB rejects it."""
        tricks = []
        for i, w in enumerate(self.stage_a.windows):
            t = self.verdict.tricks[i]
            obs = self.observations[i]
            c = t.landing
            tricks.append(
                {
                    "pop_ms": _ms(w.pop_ms),
                    "apex_ms": _ms(w.apex_ms),
                    "land_ms": _ms(w.land_ms),
                    "peak_elevation": _num(w.peak_elevation),
                    "takeoff_ms": _ms(obs.takeoff_ms) if obs else None,
                    "touchdown_ms": _ms(obs.touchdown_ms) if obs else None,
                    "outcome": t.outcome,
                    "confidence": _num(t.confidence, 2),
                    "pose_found": _num(obs.pose.found_frac, 3) if obs else None,
                    "feet_visibility": _num(obs.pose.feet_visibility(), 3) if obs else None,
                    "landing": None
                    if c is None
                    else {
                        "touchdown_ms": _ms(c.touchdown_ms),
                        "sampled": c.sampled,
                        "judged": c.judged,
                        "on_board": c.on_board,
                        "implausible_boards": c.implausible_boards,
                        "stance": _num(c.stance),
                        "board_offset_range": _num(c.board_offset_range),
                    },
                    "measurements": self.measurements[i],
                    "subscores": self.subscores[i],
                }
            )
        return {
            "schema": DETAILS_SCHEMA,
            "clip": {
                "duration_ms": self.info.duration_ms,
                "fps": _num(float(self.info.output_fps), 2),
                "skater_height_frac": _num(self.stage_a.skater_height_frac),
                "skater_coverage": _num(self.stage_a.skater_coverage, 3),
                "brightness": _num(self.stage_a.brightness, 1),
            },
            "tricks": tricks,
            "timings_s": {k: round(v, 2) for k, v in self.timings_s.items()},
        }


def _num(v: float | None, nd: int = 4) -> float | None:
    return None if v is None or not np.isfinite(v) else round(float(v), nd)


def _ms(v: float | None) -> int | None:
    return None if v is None or not np.isfinite(v) else int(round(v))


def analyze(processed: str, yolox_path: str, pose_path: str, label: str = "") -> AnalysisResult:
    """Analyze a processed (media.transcode) clip. `label` names it in logs."""
    timings: dict[str, float] = {}
    t_start = time.perf_counter()
    info = media.probe(processed)
    stage_a = localize.analyze(processed, info, yolox_path)
    timings |= {f"stage_a_{k}": v for k, v in stage_a.timings_s.items()}

    observations: list[stage_b.TrickObservation | None] = []
    t0 = time.perf_counter()
    for n, window in enumerate(stage_a.windows, 1):
        try:
            obs = stage_b.observe(processed, info, stage_a, window, yolox_path, pose_path)
        except Exception:
            log.exception("analyzer: %s stage B trick %d crashed, leaving it out", label, n)
            obs = None
        observations.append(obs)
    timings["stage_b"] = time.perf_counter() - t0

    t0 = time.perf_counter()
    verdict = gate.assess_clip(stage_a, observations, info.duration_ms)
    measurements: list[dict | None] = [None] * len(observations)
    subscores: list[dict | None] = [None] * len(observations)
    crashed = False
    for i, t in enumerate(verdict.tricks):
        if t.landing is None:  # failed an earlier check, nothing to measure
            continue
        landed = t.outcome == Verdict.LANDED
        try:
            measurements[i] = measure.measure(t.obs, t.landing.touchdown_ms, info.duration_ms)
            if landed:
                subscores[i] = calibration.subscores(measurements[i])
        except Exception:
            log.exception("analyzer: %s measuring trick %d crashed", label, i + 1)
            measurements[i] = subscores[i] = None
            if landed:  # bails aren't scored, so only a landed trick fails
                observations[i] = None
                crashed = True
    if crashed:
        verdict = gate.assess_clip(stage_a, observations, info.duration_ms)

    breakdown = steeze = None
    if verdict.failure_reason is None:
        landed_scores = [s for s in subscores if s is not None]
        breakdown, steeze = calibration.aggregate(landed_scores)
    timings["judge_and_score"] = time.perf_counter() - t0
    timings["total"] = time.perf_counter() - t_start
    return AnalysisResult(
        info=info,
        stage_a=stage_a,
        observations=observations,
        verdict=verdict,
        measurements=measurements,
        subscores=subscores,
        breakdown=breakdown,
        steeze_score=steeze,
        timings_s=timings,
    )
