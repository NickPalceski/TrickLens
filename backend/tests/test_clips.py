"""Integration tests for the clip lifecycle: create -> upload -> complete ->
worker -> tag -> publish. Runs against real Postgres and real LocalStack S3
(the same ones `make up` starts) — only Cognito is faked, the same trick
test_auth.py uses to avoid needing a real token for every route test: a real
user row is seeded directly, and only `get_current_claims` is overridden to
point at it, so `get_current_user`'s DB lookup is exercised for real.
"""

import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from app import worker
from app.api import deps
from app.api.routes import clips as clips_routes
from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus
from app.models.user import User

# Explicit, not just relying on pyproject.toml's default: app.db's engine is
# a module-level singleton whose asyncpg pool is bound to whichever event
# loop first used it, so every test here needs to share one loop rather than
# each getting its own — see the comment on asyncio_default_fixture_loop_scope
# in pyproject.toml for the full story. Both the tests (this mark) and the
# fixture below (@pytest_asyncio.fixture(loop_scope=...)) need to say so
# explicitly — a plain @pytest.fixture on an async generator pulls in
# pytest-asyncio's legacy function-scoped event_loop fixture internally,
# which conflicts with this mark rather than matching it.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def authed_client():
    sub = f"test-{uuid.uuid4()}"
    username = f"tester{uuid.uuid4().hex[:8]}"
    async with SessionLocal() as db:
        db.add(User(cognito_sub=sub, username=username))
        await db.commit()

    async def _fake_claims():
        return {"sub": sub, "email": "tester@example.com"}

    app.dependency_overrides[deps.get_current_claims] = _fake_claims
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


def _reachable_from_container(url: str) -> str:
    """The API rewrites presigned URLs to AWS_PUBLIC_ENDPOINT_URL
    (localhost:4566) for clients on the host. This test suite runs *inside*
    the api container, where LocalStack is the Docker-network host — undo the
    rewrite so the PUT actually connects."""
    s = get_settings()
    if s.aws_public_endpoint_url and s.boto_endpoint:
        return url.replace(s.aws_public_endpoint_url, s.boto_endpoint, 1)
    return url


async def _create_and_upload(client: httpx.AsyncClient, **extra) -> dict:
    resp = await client.post(
        "/clips",
        json={"content_type": "video/mp4", "duration_ms": 5000, "source_fps": 60} | extra,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    put = httpx.put(
        _reachable_from_container(body["upload_url"]),
        content=b"fake video bytes",
        headers={"Content-Type": "video/mp4"},
    )
    assert put.status_code == 200, put.text
    return body["clip"]


class _CapturingQueue:
    """Stands in for app.services.queue's Queue on POST /complete.

    The real queue is shared with `make up`'s worker container, which polls
    it with ANALYZER=real. Since 6a, that container would race this test for
    the clip and ffprobe its fake upload bytes into `unanalyzable`. This
    test runs the worker itself anyway, so it only needs to check what
    would have been sent. SQS reachability is covered by /health/deep and
    test_health.py.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def enqueue(self, body: dict) -> None:
        self.sent.append(body)


async def test_full_upload_to_publish_flow(authed_client, monkeypatch):
    queue = _CapturingQueue()
    monkeypatch.setattr(clips_routes, "get_queue", lambda: queue)

    clip = await _create_and_upload(authed_client)
    clip_id = clip["id"]
    assert clip["status"] == "draft"

    resp = await authed_client.post(f"/clips/{clip_id}/complete")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"
    assert queue.sent == [{"clip_id": clip_id, "s3_key": f"raw/{clip_id}.mp4"}]

    # Runs the worker's processing function directly rather than through
    # real SQS timing — deterministic, and this is the same code path the
    # poll loop and the Lambda handler both call.
    await worker._process_message(queue.sent[0])

    resp = await authed_client.get(f"/clips/{clip_id}")
    body = resp.json()
    if body["status"] == "unanalyzable":
        pytest.skip("stub's ~10% failure branch landed on this clip id — not a bug")
    assert body["status"] == "analyzed"
    assert set(body["analysis"]["steeze_breakdown"]) == set(worker._SUBSCORES)
    # Per-trick detail out of analyses.details (6c-3), the stub's one trick.
    (trick,) = body["analysis"]["tricks"]
    assert trick["outcome"] == "landed"
    assert trick["subscores"] == body["analysis"]["steeze_breakdown"]
    assert trick["takeoff_ms"] < trick["touchdown_ms"]

    resp = await authed_client.post(f"/clips/{clip_id}/publish")
    assert resp.status_code == 422, "shouldn't be publishable before any trick is tagged"

    resp = await authed_client.post(f"/clips/{clip_id}/tricks", json={"tricks": ["Kickflip"]})
    assert resp.status_code == 200, resp.text
    assert [t["canonical_name"] for t in resp.json()["tricks"]] == ["kickflip"]

    resp = await authed_client.post(f"/clips/{clip_id}/publish")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "published"


async def test_complete_without_upload_fails(authed_client):
    resp = await authed_client.post(
        "/clips", json={"content_type": "video/mp4", "duration_ms": 1000, "source_fps": 30}
    )
    clip_id = resp.json()["clip"]["id"]

    resp = await authed_client.post(f"/clips/{clip_id}/complete")
    assert resp.status_code == 422


async def test_tag_before_analyzed_fails(authed_client):
    clip = await _create_and_upload(authed_client)
    resp = await authed_client.post(f"/clips/{clip['id']}/tricks", json={"tricks": ["Ollie"]})
    assert resp.status_code == 409


async def test_other_users_draft_is_invisible(authed_client):
    clip = await _create_and_upload(authed_client)

    sub = f"test-{uuid.uuid4()}"
    async with SessionLocal() as db:
        db.add(User(cognito_sub=sub, username=f"other{uuid.uuid4().hex[:8]}"))
        await db.commit()

    async def _other_claims():
        return {"sub": sub, "email": "other@example.com"}

    app.dependency_overrides[deps.get_current_claims] = _other_claims
    resp = await authed_client.get(f"/clips/{clip['id']}")
    assert resp.status_code == 404



async def test_clip_without_analysis_is_tagged_up_front_and_never_scored(
    authed_client, monkeypatch
):
    """`analyze: false` (F4): tags go on from creation, the worker only
    transcodes (the stub here: the API image has no ffmpeg), and the clip
    becomes `analyzed` with no score and no analysis."""
    queue = _CapturingQueue()
    monkeypatch.setattr(clips_routes, "get_queue", lambda: queue)

    clip = await _create_and_upload(authed_client, analyze=False)
    clip_id = clip["id"]
    assert clip["analyze"] is False

    resp = await authed_client.post(f"/clips/{clip_id}/tricks", json={"tricks": ["Ollie"]})
    assert resp.status_code == 200, "a clip without analysis can be tagged while still a draft"
    resp = await authed_client.post(
        f"/clips/{clip_id}/tricks", json={"tricks": [{"name": "Ollie", "analysis_index": 0}]}
    )
    assert resp.status_code == 422, "nothing was analyzed, so no analysis_index fits"

    resp = await authed_client.post(f"/clips/{clip_id}/complete")
    assert resp.json()["status"] == "queued", "still queued: the worker transcodes it"
    resp = await authed_client.post(f"/clips/{clip_id}/publish")
    assert resp.status_code == 409, "not publishable until the worker is done"

    await worker._process_message(queue.sent[0])

    body = (await authed_client.get(f"/clips/{clip_id}")).json()
    assert body["status"] == "analyzed"
    assert body["analysis"] is None
    assert body["steeze_score"] is None
    assert [t["canonical_name"] for t in body["tricks"]] == ["ollie"]

    resp = await authed_client.post(f"/clips/{clip_id}/publish")
    assert resp.status_code == 200, resp.text


async def _analyzed_clip_with(client: httpx.AsyncClient, outcomes: list[str]) -> str:
    """An analyzed clip of the test user's whose analysis found these
    tricks, inserted directly (the stub always finds one)."""
    me = (await client.get("/users/me")).json()
    async with SessionLocal() as db:
        clip = Clip(
            user_id=uuid.UUID(me["id"]),
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=ClipStatus.ANALYZED,
            steeze_score=Decimal("75.0"),
        )
        db.add(clip)
        await db.flush()
        tricks = [
            {"outcome": o, "pop_ms": 1000 * i, "land_ms": 1000 * i + 400, "confidence": 0.9}
            for i, o in enumerate(outcomes)
        ]
        db.add(
            Analysis(
                clip_id=clip.id,
                model_version="test",
                confidence=Decimal("0.9"),
                details={"schema": 1, "tricks": tricks},
            )
        )
        await db.commit()
        return str(clip.id)


async def test_tags_name_analyzed_tricks_and_can_skip_one(authed_client):
    """A step-off at the end comes back as an analyzed "trick" (6d-2). The
    skater names the real ones by index and leaves it untagged."""
    clip_id = await _analyzed_clip_with(
        authed_client, ["landed", "bailed", "clip ends too soon after the landing"]
    )
    url = f"/clips/{clip_id}/tricks"

    resp = await authed_client.post(
        url,
        json={
            "tricks": [
                {"name": "Kickflip", "analysis_index": 0},
                {"name": "Heelflip", "analysis_index": 1},
            ]
        },
    )
    assert resp.status_code == 200, resp.text
    assert [(t["canonical_name"], t["analysis_index"]) for t in resp.json()["tricks"]] == [
        ("kickflip", 0),
        ("heelflip", 1),
    ]
    # Still stored after the request's session is gone (see the viewonly gotcha).
    body = (await authed_client.get(f"/clips/{clip_id}")).json()
    assert [t["analysis_index"] for t in body["tricks"]] == [0, 1]

    out_of_range = {"tricks": [{"name": "Ollie", "analysis_index": 3}]}
    assert (await authed_client.post(url, json=out_of_range)).status_code == 422
    twice = {"tricks": [{"name": "A", "analysis_index": 0}, {"name": "B", "analysis_index": 0}]}
    assert (await authed_client.post(url, json=twice)).status_code == 422

    # Plain names still work, tagging by position (the pre-F4 behaviour).
    resp = await authed_client.post(url, json={"tricks": ["Ollie"]})
    assert resp.status_code == 200
    assert resp.json()["tricks"][0]["analysis_index"] is None
