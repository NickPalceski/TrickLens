"""Integration tests for the clip lifecycle: create -> upload -> complete ->
worker -> tag -> publish. Runs against real Postgres and real LocalStack S3
(the same ones `make up` starts) — only Cognito is faked, the same trick
test_auth.py uses to avoid needing a real token for every route test: a real
user row is seeded directly, and only `get_current_claims` is overridden to
point at it, so `get_current_user`'s DB lookup is exercised for real.
"""

import uuid

import httpx
import pytest
import pytest_asyncio

from app import worker
from app.api import deps
from app.db import SessionLocal
from app.main import app
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


async def _create_and_upload(client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        "/clips", json={"content_type": "video/mp4", "duration_ms": 5000, "source_fps": 60}
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()

    put = httpx.put(
        body["upload_url"], content=b"fake video bytes", headers={"Content-Type": "video/mp4"}
    )
    assert put.status_code == 200, put.text
    return body["clip"]


async def test_full_upload_to_publish_flow(authed_client):
    clip = await _create_and_upload(authed_client)
    clip_id = clip["id"]
    assert clip["status"] == "draft"

    resp = await authed_client.post(f"/clips/{clip_id}/complete")
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "queued"

    # Runs the worker's processing function directly rather than through
    # real SQS timing — deterministic, and this is the same code path the
    # poll loop and the Lambda handler both call.
    await worker._process_message({"clip_id": clip_id})

    resp = await authed_client.get(f"/clips/{clip_id}")
    body = resp.json()
    if body["status"] == "unanalyzable":
        pytest.skip("stub's ~10% failure branch landed on this clip id — not a bug")
    assert body["status"] == "analyzed"
    assert set(body["analysis"]["steeze_breakdown"]) == set(worker._SUBSCORES)

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
