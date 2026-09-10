"""Integration tests for follows + the home feed (step 4a).

Same setup as test_clips.py: real Postgres and LocalStack, only Cognito
faked. Published clips are inserted directly rather than driven through the
whole upload pipeline — that path is already covered by test_clips.py, and
these tests only care about follow edges and feed ordering.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app.api import deps
from app.db import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.enums import ClipStatus
from app.models.user import User

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _new_user() -> tuple[str, uuid.UUID, str]:
    sub = f"test-{uuid.uuid4()}"
    username = f"u{uuid.uuid4().hex[:10]}"
    async with SessionLocal() as db:
        user = User(cognito_sub=sub, username=username)
        db.add(user)
        await db.commit()
        return sub, user.id, user.username


def _act_as(sub: str) -> None:
    async def _claims():
        return {"sub": sub, "email": f"{sub}@example.com"}

    # get_optional_user is a separate auth path from get_current_claims (no
    # token required), so faking the latter isn't enough for the public
    # routes that read `viewer` — override it directly too.
    async def _optional_user(db: deps.DbSession):
        return await db.scalar(select(User).where(User.cognito_sub == sub))

    app.dependency_overrides[deps.get_current_claims] = _claims
    app.dependency_overrides[deps.get_optional_user] = _optional_user


async def _publish_clip(user_id: uuid.UUID, published_at: datetime) -> uuid.UUID:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=ClipStatus.PUBLISHED,
            published_at=published_at,
            steeze_score=Decimal("70.0"),
        )
        db.add(clip)
        await db.commit()
        return clip.id


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_follow_unfollow_roundtrip(client):
    a_sub, _, _ = await _new_user()
    _, _, b_name = await _new_user()

    _act_as(a_sub)
    r = await client.post(f"/users/{b_name}/follow")
    assert r.status_code == 201, r.text
    assert r.json()["followed_by_me"] is True
    assert r.json()["follower_count"] == 1

    r = await client.post(f"/users/{b_name}/follow")
    assert r.status_code == 409

    r = await client.get(f"/users/{b_name}")
    assert r.json()["followed_by_me"] is True

    r = await client.delete(f"/users/{b_name}/follow")
    assert r.status_code == 200
    assert r.json()["followed_by_me"] is False
    assert r.json()["follower_count"] == 0

    # Idempotent — unfollowing again is a no-op 200, not an error.
    r = await client.delete(f"/users/{b_name}/follow")
    assert r.status_code == 200


async def test_cannot_follow_self(client):
    a_sub, _, a_name = await _new_user()
    _act_as(a_sub)
    r = await client.post(f"/users/{a_name}/follow")
    assert r.status_code == 422


async def test_public_profile_for_anon_viewer_has_no_follow_state(client):
    _, _, name = await _new_user()
    app.dependency_overrides.clear()  # no bearer token
    r = await client.get(f"/users/{name}")
    assert r.status_code == 200
    assert r.json()["followed_by_me"] is False


async def test_feed_shows_followed_excludes_others_and_self(client):
    a_sub, a_id, _ = await _new_user()
    _, b_id, b_name = await _new_user()
    _, c_id, _ = await _new_user()

    now = datetime.now(UTC)
    b_clip = await _publish_clip(b_id, now - timedelta(minutes=1))
    await _publish_clip(c_id, now)  # c is not followed
    await _publish_clip(a_id, now)  # a's own clip

    _act_as(a_sub)
    await client.post(f"/users/{b_name}/follow")

    r = await client.get("/feed")
    assert r.status_code == 200
    assert [item["id"] for item in r.json()["items"]] == [str(b_clip)]
    assert r.json()["items"][0]["author"]["username"] == b_name


async def test_feed_keyset_pagination(client):
    a_sub, _, _ = await _new_user()
    _, b_id, b_name = await _new_user()

    now = datetime.now(UTC)
    made = [await _publish_clip(b_id, now - timedelta(minutes=i)) for i in range(3)]

    _act_as(a_sub)
    await client.post(f"/users/{b_name}/follow")

    r = await client.get("/feed", params={"limit": 2})
    page1 = r.json()
    assert [i["id"] for i in page1["items"]] == [str(made[0]), str(made[1])]
    assert page1["next_cursor"] is not None

    r = await client.get("/feed", params={"limit": 2, "cursor": page1["next_cursor"]})
    page2 = r.json()
    assert [i["id"] for i in page2["items"]] == [str(made[2])]
    assert page2["next_cursor"] is None
