"""calibration.py (measurements → subscores → steeze, 6c-3) and the API's
`analysis.tricks` (serializers.analysis_out). Pure: no database, no CV,
so both images run it."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.analyzer import calibration as C
from app.api.serializers import analysis_out
from app.models.clip import Analysis

# The tripod kickflip's measurements (docs/components/analyzer.md,
# Subscores, as built (6c-3)): the sanity anchor for the guessed ramps.
KICKFLIP = {
    "pop_height": 0.3795, "settle_ms": 50.0, "torso_sway_deg": 2.05, "arm_flail": 0.6203,
    "rollaway_on_board_frac": 1.0, "foot_down": False, "stomp_error": 0.1217,
    "arm_ratio": 1.926, "leg_ratio": 1.2121, "catch_frac": 0.5,
}  # fmt: skip


def test_ramps_clamp_at_both_ends():
    assert C.ramp(-5.0, C.POP_HEIGHT) == 20.0
    assert C.ramp(5.0, C.POP_HEIGHT) == 100.0
    assert C.ramp(10_000.0, C.SETTLE_MS) == 20.0


@pytest.mark.parametrize(
    "key,better,worse",
    [
        ("pop_height", 0.4, 0.2),
        ("settle_ms", 100.0, 400.0),
        ("torso_sway_deg", 3.0, 10.0),
        ("arm_flail", 0.3, 0.7),
        ("stomp_error", 0.02, 0.15),
        ("leg_ratio", 1.1, 1.5),
        ("arm_ratio", 1.3, 2.0),
        ("catch_frac", 0.6, 0.1),
        ("rollaway_on_board_frac", 1.0, 0.6),
    ],
)
def test_every_measurement_scores_in_the_right_direction(key, better, worse):
    sub = {k: v for k, v in C.subscores({key: better}).items() if v is not None}
    worse_sub = {k: v for k, v in C.subscores({key: worse}).items() if v is not None}
    (name,) = sub
    assert sub[name] > worse_sub[name]


def test_missing_measurements_are_na_not_zero():
    assert C.subscores({}) == dict.fromkeys(C.SUBSCORES)


def test_a_foot_down_caps_roll_away():
    m = {"rollaway_on_board_frac": 1.0, "foot_down": True}
    assert C.subscores(m)["roll_away"] == C.FOOT_DOWN_CAP


def test_the_sketchy_kickflip_lands_mid_to_high_not_near_100():
    s = C.subscores(KICKFLIP)
    assert all(v is not None for v in s.values())
    _, steeze = C.aggregate([s])
    assert 65 <= steeze <= 85
    # Its windmilling arms cost it landing stability.
    assert s["landing_stability"] < C.subscores({**KICKFLIP, "arm_flail": 0.2})["landing_stability"]


def test_aggregate_averages_per_subscore_skipping_na():
    a = dict.fromkeys(C.SUBSCORES, 60.0) | {"catch": None}
    b = dict.fromkeys(C.SUBSCORES, 80.0) | {"catch": 90.0}
    breakdown, steeze = C.aggregate([a, b])
    assert breakdown["pop"] == 70.0
    assert breakdown["catch"] == 90.0  # only b has one
    assert steeze == round((70.0 * 5 + 90.0) / 6, 1)


def test_aggregate_keeps_every_key_and_nulls_one_na_everywhere():
    a = dict.fromkeys(C.SUBSCORES, 50.0) | {"catch": None}
    breakdown, steeze = C.aggregate([a])
    assert set(breakdown) == set(C.SUBSCORES) and breakdown["catch"] is None
    assert steeze == 50.0


# --- analysis.tricks ----------------------------------------------------------


def _analysis(details) -> Analysis:
    return Analysis(
        id=uuid.uuid4(),
        clip_id=uuid.uuid4(),
        model_version=C.MODEL_VERSION,
        confidence=Decimal("0.90"),
        steeze_breakdown=None,
        failure_reason="no landed trick detected",
        details=details,
        created_at=datetime.now(UTC),
    )


def test_analysis_tricks_come_from_details_with_stage_a_fallbacks():
    details = {
        "schema": 1,
        "tricks": [
            {"pop_ms": 1100, "land_ms": 1300, "takeoff_ms": 1083, "touchdown_ms": 1333,
             "outcome": "bailed", "confidence": 0.89, "subscores": None},
            {"pop_ms": 3000, "land_ms": 3400, "takeoff_ms": None, "touchdown_ms": None,
             "outcome": "analysis failed for this trick", "confidence": 0.0, "subscores": None},
        ],
    }  # fmt: skip
    out = analysis_out(_analysis(details))
    assert [(t.outcome, t.takeoff_ms, t.touchdown_ms) for t in out.tricks] == [
        ("bailed", 1083, 1333),
        ("analysis failed for this trick", 3000, 3400),
    ]


def test_analysis_without_details_has_no_tricks():
    assert analysis_out(_analysis(None)).tricks == []


def test_subscores_come_out_in_their_fixed_order():
    """JSONB reorders keys; the API puts them back."""
    a = _analysis(None)
    a.steeze_breakdown = {"stomp": 1.0, "pop": 2.0, "catch": None, "roll_away": 3.0,
                          "compactness": 4.0, "landing_stability": 5.0}  # fmt: skip
    assert list(analysis_out(a).steeze_breakdown) == list(C.SUBSCORES)


# --- make calibrate (calibrate.py): judgments, pairing, fitting (6d-1) ----------

from app.analyzer import calibrate as T  # noqa: E402


def _judged(outcome="landed", at=None, **scores):
    return T.JudgedTrick(
        outcome, at, {k: (None if v == "n/a" else float(v)) for k, v in scores.items()}
    )


def _found(pop_ms=1200, outcome="landed", **m):
    return {"pop_ms": pop_ms, "outcome": outcome, "measurements": m or None}


def test_judgments_parse_and_reject_mistakes():
    ok = {"clip": [{"file": "a.mov", "trick": [{"outcome": "landed", "pop": 70, "catch": "n/a"}]}]}
    [clip] = T.parse_judgments(ok)
    assert clip.tricks[0].scores == {"pop": 70.0, "catch": None}
    bad = [
        {"clip": [{"file": "a.mov", "trick": [{"outcome": "stomped"}]}]},  # unknown outcome
        {"clip": [{"file": "a.mov", "trick": [{"outcome": "landed", "pops": 70}]}]},  # typo
        {"clip": [{"file": "a.mov", "trick": [{"outcome": "landed", "pop": 170}]}]},  # range
        {"clip": [{"file": "a.mov", "trick": [{"outcome": "bailed", "pop": 70}]}]},  # bail scored
        {"clip": [{"file": "a.mov", "trick": [{"outcome": "landed"}, {"outcome": "landed"}]}]},
    ]
    for data in bad:
        with pytest.raises(ValueError):
            T.parse_judgments(data)


def test_pairing_by_order_and_by_time():
    clip = T.JudgedClip("a.mov", [_judged(), _judged("bailed")])
    found = [_found(1000), _found(3000, "bailed")]
    assert [p.found["pop_ms"] for p in T.pair_tricks(clip, found)] == [1000, 3000]

    clip = T.JudgedClip("a.mov", [_judged(at=3.1), _judged("bailed", at=6.0)])
    pairs = T.pair_tricks(clip, [_found(1000), _found(3000)])
    assert [(p.judged and p.judged.at_s, p.found and p.found["pop_ms"]) for p in pairs] == [
        (3.1, 3000),  # nearest pop
        (6.0, None),  # nothing within MATCH_WITHIN_S: missed
        (None, 1000),  # found, but you didn't judge it: extra
    ]


def test_a_fit_recovers_a_known_ramp():
    """Your scores follow pop 0.1 -> 30, 0.4 -> 90 exactly: the fit finds
    that line, kept on the current 20 -> 100 end scores."""
    pts = [(x, 30 + 200 * (x - 0.1)) for x in (0.1, 0.15, 0.2, 0.3, 0.35, 0.4)]
    f = T.fit_ramp("pop_height", "POP_HEIGHT", pts)
    assert f.status == "fitted" and f.r == pytest.approx(1.0)
    xa, sa, xb, sb = f.proposed
    assert (sa, sb) == (20.0, 100.0)
    assert C.ramp(0.25, f.proposed) == pytest.approx(60.0)


def test_a_fit_refuses_too_little_a_flip_or_a_weak_link():
    assert T.fit_ramp("pop_height", "POP_HEIGHT", [(0.2, 50)] * 3).status == "too few"
    higher_is_worse = [(x, 100 - 100 * x) for x in (0.1, 0.2, 0.3, 0.4, 0.5)]
    f = T.fit_ramp("pop_height", "POP_HEIGHT", higher_is_worse)
    assert f.status == "flips direction" and f.proposed == C.POP_HEIGHT
    noise = [(0.1, 60), (0.2, 40), (0.3, 70), (0.4, 45), (0.5, 62), (0.6, 50)]
    assert T.fit_ramp("pop_height", "POP_HEIGHT", noise).status == "weak"


def test_foot_down_tricks_stay_out_of_the_roll_away_fit():
    clip = T.JudgedClip("a.mov", [_judged(roll_away=30)])
    pairs = T.pair_tricks(clip, [_found(rollaway_on_board_frac=1.0, foot_down=True)])
    assert T.training_points(pairs, "roll_away", "rollaway_on_board_frac") == []


def test_the_report_fits_and_compares_clip_scores():
    """Six landed tricks whose pop scores follow a different line than the
    guess: the report proposes it, and the fitted error beats today's."""
    clips, pairs = [], []
    for i, h in enumerate((0.1, 0.15, 0.2, 0.3, 0.35, 0.4)):
        c = T.JudgedClip(f"c{i}.mov", [_judged(pop=30 + 200 * (h - 0.1))])
        clips.append(c)
        pairs += T.pair_tricks(c, [_found(pop_height=h)])
    now = T.errors(pairs, C.current_ramps())
    fitted = T.errors(pairs, {n: f.proposed for n, f in T.fit_all(pairs).items()})
    assert fitted["pop"] < now["pop"] and fitted["pop"] == pytest.approx(0.0, abs=0.1)
    assert T.leave_one_out(pairs)["pop"] == pytest.approx(0.0, abs=0.5)
    text = T.report(clips, pairs)
    assert "agree on landed vs not: 6/6" in text
    assert (
        "POP_HEIGHT = " in text and "SETTLE_MS = (100.0, 100.0, 600.0, 20.0)  # unchanged" in text
    )
