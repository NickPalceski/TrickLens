"""Unit tests for the stub analyzer. Pure function — no DB, no SQS."""

import uuid

from app.worker import _FAILURE_REASONS, _SUBSCORES, _stub_score


def test_deterministic_for_same_clip_id():
    clip_id = uuid.uuid4()
    assert _stub_score(clip_id) == _stub_score(clip_id)


def test_analyzed_shape_has_all_subscores():
    for _ in range(200):
        result = _stub_score(uuid.uuid4())
        if "steeze_breakdown" in result:
            assert set(result["steeze_breakdown"]) == set(_SUBSCORES)
            assert 0 <= result["confidence"] <= 1
            assert result["steeze_score"] == round(
                sum(result["steeze_breakdown"].values()) / len(_SUBSCORES), 1
            )
            return
    raise AssertionError("no analyzed result found in 200 tries — check the failure rate")


def test_unanalyzable_shape_has_a_reason():
    for _ in range(200):
        result = _stub_score(uuid.uuid4())
        if "steeze_breakdown" not in result:
            assert result["failure_reason"] in _FAILURE_REASONS
            assert 0 <= result["confidence"] <= 1
            return
    raise AssertionError("no unanalyzable result found in 200 tries — check the failure rate")
