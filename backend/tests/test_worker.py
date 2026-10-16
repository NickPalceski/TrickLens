"""The stub analyzer (pure function), the worker's last-receive give-up
(real Postgres, no SQS), and the stuck-clip sweep (app/sweep.py, 6c-3)."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import sweep, worker
from app.analyzer.reasons import ANALYSIS_FAILED
from app.db import SessionLocal
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.models.user import User
from app.worker import _FAILURE_REASONS, _SUBSCORES, _stub_score


def test_deterministic_for_same_clip_id():
    clip_id = uuid.uuid4()
    assert _stub_score(clip_id) == _stub_score(clip_id)


def test_analyzed_shape_has_all_subscores():
    for _ in range(200):
        result = _stub_score(uuid.uuid4())
        if "steeze_breakdown" in result:
            # All six keys, null where n/a (6c-3); the score averages the rest.
            assert set(result["steeze_breakdown"]) == set(_SUBSCORES)
            assert 0 <= result["confidence"] <= 1
            present = [v for v in result["steeze_breakdown"].values() if v is not None]
            assert result["steeze_score"] == round(sum(present) / len(present), 1)
            # The real analyzer's details shape, so the API is built against it.
            (trick,) = result["details"]["tricks"]
            assert trick["outcome"] == "landed"
            assert trick["subscores"] == result["steeze_breakdown"]
            return
    raise AssertionError("no analyzed result found in 200 tries — check the failure rate")


def test_stub_sometimes_has_a_subscore_na():
    for _ in range(200):
        result = _stub_score(uuid.uuid4())
        if "steeze_breakdown" in result and result["steeze_breakdown"]["catch"] is None:
            return
    raise AssertionError("catch was never n/a in 200 tries")


def test_unanalyzable_shape_has_a_reason():
    for _ in range(200):
        result = _stub_score(uuid.uuid4())
        if "steeze_breakdown" not in result:
            assert result["failure_reason"] in _FAILURE_REASONS
            assert 0 <= result["confidence"] <= 1
            return
    raise AssertionError("no unanalyzable result found in 200 tries — check the failure rate")


# --- last SQS receive (real Postgres) -----------------------------------------
# No upload and no media: these run in the API image too.


async def _clip(status: ClipStatus, updated_at: datetime | None = None) -> uuid.UUID:
    async with SessionLocal() as db:
        user = User(cognito_sub=f"test-{uuid.uuid4()}", username=f"w{uuid.uuid4().hex[:10]}")
        db.add(user)
        await db.flush()
        clip = Clip(user_id=user.id, status=status, s3_key=f"raw/{uuid.uuid4()}.mp4")
        db.add(clip)
        await db.flush()
        if updated_at is not None:
            clip.updated_at = updated_at  # explicit, so onupdate=now() doesn't apply
        await db.commit()
        return clip.id


async def _load(clip_id: uuid.UUID) -> tuple[Clip, list[Analysis]]:
    async with SessionLocal() as db:
        clip = await db.get(Clip, clip_id)
        analyses = list(await db.scalars(select(Analysis).where(Analysis.clip_id == clip_id)))
    return clip, analyses


def _stale() -> datetime:
    return datetime.now(UTC) - worker.ANALYZING_LEASE - timedelta(seconds=30)


async def _must_not_run(_clip):
    raise AssertionError("the analyzer ran")


@pytest.mark.asyncio(loop_scope="session")
async def test_last_receive_gives_up_on_a_clip_whose_runs_died(monkeypatch):
    """Earlier runs died (timeout, native abort) and left it `analyzing`:
    the last receive marks it unanalyzable instead of crashing into the DLQ."""
    monkeypatch.setattr(worker, "_analyze_real", _must_not_run)
    clip_id = await _clip(ClipStatus.ANALYZING, _stale())

    await worker._process_message({"clip_id": str(clip_id)}, worker.MAX_RECEIVES)

    clip, analyses = await _load(clip_id)
    assert clip.status == ClipStatus.UNANALYZABLE
    assert clip.steeze_score is None
    assert [a.failure_reason for a in analyses] == [ANALYSIS_FAILED]


@pytest.mark.asyncio(loop_scope="session")
async def test_last_receive_still_processes_a_clip_never_tried(monkeypatch):
    """Still `queued` on its last receive means no run ever claimed it, so
    there's nothing to give up on yet."""

    async def stub_analysis(_clip):
        return worker._stub_score(_clip.id)

    monkeypatch.setattr(worker, "_analyze_real", stub_analysis)
    clip_id = await _clip(ClipStatus.QUEUED)

    await worker._process_message({"clip_id": str(clip_id)}, worker.MAX_RECEIVES)

    clip, analyses = await _load(clip_id)
    assert clip.status in (ClipStatus.ANALYZED, ClipStatus.UNANALYZABLE)  # stub scorer's 10%
    assert [a.model_version for a in analyses] == [worker.model_version()]
    assert analyses[0].failure_reason != ANALYSIS_FAILED


@pytest.mark.asyncio(loop_scope="session")
async def test_last_receive_leaves_a_live_run_alone(monkeypatch):
    monkeypatch.setattr(worker, "_analyze_real", _must_not_run)
    clip_id = await _clip(ClipStatus.ANALYZING, datetime.now(UTC))

    await worker._process_message({"clip_id": str(clip_id)}, worker.MAX_RECEIVES)

    clip, analyses = await _load(clip_id)
    assert clip.status == ClipStatus.ANALYZING
    assert analyses == []


@pytest.mark.asyncio(loop_scope="session")
async def test_lambda_handler_passes_the_receive_count(monkeypatch):
    seen = []

    async def fake(body, receive_count=1):
        seen.append((body, receive_count))

    monkeypatch.setattr(worker, "_process_message", fake)
    record = {"body": '{"clip_id": "x"}', "attributes": {"ApproximateReceiveCount": "3"}}
    await asyncio.to_thread(worker.lambda_handler, {"Records": [record]}, None)
    assert seen == [({"clip_id": "x"}, 3)]


@pytest.mark.asyncio(loop_scope="session")
async def test_lambda_handler_survives_a_warm_container(monkeypatch):
    """Lambda reuses a warm container: lambda_handler runs again in the same
    process, with a new event loop (asyncio.run per invocation). Pooled
    connections from the previous loop must not leak into the next one, or
    the second message dies with "attached to a different loop" before it
    claims its clip (the 6c-2 prod check's second kickflip)."""
    from app.db import engine

    async def stub_analysis(_clip):
        return worker._stub_score(_clip.id)

    monkeypatch.setattr(worker, "_analyze_real", stub_analysis)
    ids = [await _clip(ClipStatus.QUEUED) for _ in range(2)]
    # Start like a fresh container: no pooled connections. (Creating the
    # clips above pooled one from pytest's own loop.)
    await engine.dispose()
    for clip_id in ids:  # two invocations, same "container" (this process)
        record = {
            "body": f'{{"clip_id": "{clip_id}"}}',
            "attributes": {"ApproximateReceiveCount": "1"},
        }
        await asyncio.to_thread(worker.lambda_handler, {"Records": [record]}, None)
    for clip_id in ids:
        clip, _ = await _load(clip_id)
        assert clip.status in (ClipStatus.ANALYZED, ClipStatus.UNANALYZABLE)


# --- the stuck-clip sweep (real Postgres) ------------------------------------


def _hours_ago(h: float) -> datetime:
    return datetime.now(UTC) - timedelta(hours=h)


@pytest.mark.asyncio(loop_scope="session")
async def test_sweep_fails_clips_stuck_queued_or_analyzing():
    """A message that died in the DLQ before any run claimed its clip
    leaves it `queued` forever; the last-receive give-up never sees it."""
    queued = await _clip(ClipStatus.QUEUED, _hours_ago(3))
    analyzing = await _clip(ClipStatus.ANALYZING, _hours_ago(3))

    assert await sweep.run() >= 2

    for clip_id in (queued, analyzing):
        clip, analyses = await _load(clip_id)
        assert clip.status == ClipStatus.UNANALYZABLE
        assert [(a.failure_reason, a.model_version) for a in analyses] == [
            (ANALYSIS_FAILED, sweep.MODEL_VERSION)
        ]


@pytest.mark.asyncio(loop_scope="session")
async def test_sweep_leaves_recent_and_finished_clips_alone():
    recent = await _clip(ClipStatus.QUEUED, _hours_ago(1))
    running = await _clip(ClipStatus.ANALYZING, _hours_ago(0.1))
    done = await _clip(ClipStatus.ANALYZED, _hours_ago(48))

    await sweep.run()

    for clip_id, status in (
        (recent, ClipStatus.QUEUED),
        (running, ClipStatus.ANALYZING),
        (done, ClipStatus.ANALYZED),
    ):
        clip, analyses = await _load(clip_id)
        assert clip.status == status and analyses == []
