"""Integration tests for the clip and team lists the web app proposed (F4):
a user's clips, a team's clips, your drafts, your teams, and whether you've
asked to join a team.

Same setup as test_teams.py: real Postgres and LocalStack, only Cognito
faked. Every list here is scoped to users and teams the test makes, so
exact lists are safe (unlike Discover, see CLAUDE.md's shared-database
gotcha).
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


def _act_as(sub: str | None) -> None:
    """Signed in as `sub`, or signed out with None."""
    app.dependency_overrides.clear()
    if sub is None:
        return

    async def _claims():
        return {"sub": sub, "email": f"{sub}@example.com"}

    async def _optional_user(db: deps.DbSession):
        return await db.scalar(select(User).where(User.cognito_sub == sub))

    app.dependency_overrides[deps.get_current_claims] = _claims
    app.dependency_overrides[deps.get_optional_user] = _optional_user


async def _insert_clip(
    user_id: uuid.UUID,
    status: ClipStatus,
    *,
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    team_id: uuid.UUID | None = None,
) -> str:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=status,
            published_at=published_at,
            team_id=team_id,
            steeze_score=Decimal("70.0"),
        )
        if created_at is not None:
            clip.created_at = created_at
        db.add(clip)
        await db.commit()
        return str(clip.id)


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _all_pages(client, url: str, limit: int) -> list[str]:
    ids, cursor = [], None
    while True:
        params = {"limit": limit} | ({"cursor": cursor} if cursor else {})
        r = await client.get(url, params=params)
        assert r.status_code == 200, r.text
        page = r.json()
        ids += [c["id"] for c in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            return ids


async def test_user_clips_published_only_newest_first_paged(client):
    _, uid, username = await _new_user()
    _, other_id, _ = await _new_user()
    now = datetime.now(UTC)
    old = await _insert_clip(uid, ClipStatus.PUBLISHED, published_at=now - timedelta(days=2))
    new = await _insert_clip(uid, ClipStatus.PUBLISHED, published_at=now - timedelta(hours=1))
    await _insert_clip(uid, ClipStatus.ANALYZED)  # a draft: never listed
    await _insert_clip(other_id, ClipStatus.PUBLISHED, published_at=now)

    _act_as(None)  # public, like GET /users/{username}
    assert await _all_pages(client, f"/users/{username}/clips", limit=1) == [new, old]
    r = await client.get(f"/users/{username.upper()}/clips")
    assert [c["id"] for c in r.json()["items"]] == [new, old], "usernames match case-insensitively"
    assert (await client.get("/users/nobody_here_xyz/clips")).status_code == 404


async def test_my_drafts_lists_only_my_unpublished_clips(client):
    sub, uid, _ = await _new_user()
    _, other_id, _ = await _new_user()
    now = datetime.now(UTC)
    queued = await _insert_clip(uid, ClipStatus.QUEUED, created_at=now - timedelta(minutes=3))
    failed = await _insert_clip(uid, ClipStatus.UNANALYZABLE, created_at=now - timedelta(minutes=2))
    ready = await _insert_clip(uid, ClipStatus.ANALYZED, created_at=now - timedelta(minutes=1))
    await _insert_clip(uid, ClipStatus.PUBLISHED, published_at=now)
    await _insert_clip(other_id, ClipStatus.ANALYZED)

    _act_as(sub)
    assert await _all_pages(client, "/users/me/drafts", limit=2) == [ready, failed, queued]
    _act_as(None)
    assert (await client.get("/users/me/drafts")).status_code in (401, 403)


async def _found_team(client, owner_sub: str, *, join_policy: str = "open") -> str:
    """A founded team owned by `owner_sub`, with two co-founders."""
    invitees = [await _new_user() for _ in range(2)]
    slug = f"t{uuid.uuid4().hex[:10]}"
    _act_as(owner_sub)
    r = await client.post(
        "/teams",
        json={
            "name": f"Team {slug}",
            "slug": slug,
            "level": "beginner",
            "join_policy": join_policy,
            "invitee_usernames": [name for _, _, name in invitees],
        },
    )
    assert r.status_code == 201, r.text
    for sub, _, _ in invitees:
        _act_as(sub)
        assert (await client.post(f"/teams/{slug}/invites/mine/accept")).status_code == 200
    return slug


async def test_my_teams_has_my_role_and_forming_teams_i_own(client):
    me_sub, _, me_name = await _new_user()
    other_sub, _, _ = await _new_user()
    mine = await _found_team(client, me_sub)
    theirs = await _found_team(client, other_sub)
    _act_as(me_sub)
    assert (await client.post(f"/teams/{theirs}/join")).status_code == 201

    # Still forming: one I own, and one I'm only invited to found.
    _, _, a = await _new_user()
    _, _, b = await _new_user()
    forming = f"f{uuid.uuid4().hex[:10]}"
    body = {"level": "beginner", "join_policy": "open", "invitee_usernames": [a, b]}
    r = await client.post("/teams", json=body | {"name": "Forming", "slug": forming})
    assert r.status_code == 201
    _act_as(other_sub)
    invited = f"i{uuid.uuid4().hex[:10]}"
    r = await client.post(
        "/teams",
        json=body | {"name": "Invited", "slug": invited, "invitee_usernames": [me_name, a]},
    )
    assert r.status_code == 201

    _act_as(me_sub)
    r = await client.get("/users/me/teams")
    assert r.status_code == 200, r.text
    got = {t["slug"]: (t["my_role"], t["founded"]) for t in r.json()}
    assert got == {mine: ("owner", True), theirs: ("member", True), forming: ("owner", False)}


async def test_team_clips_lists_published_clips_tagged_to_it(client):
    owner_sub, owner_id, _ = await _new_user()
    slug = await _found_team(client, owner_sub)
    _act_as(owner_sub)
    team_id = (await client.get(f"/teams/{slug}")).json()["id"]
    now = datetime.now(UTC)
    tagged = await _insert_clip(
        owner_id, ClipStatus.PUBLISHED, published_at=now, team_id=uuid.UUID(team_id)
    )
    await _insert_clip(owner_id, ClipStatus.ANALYZED, team_id=uuid.UUID(team_id))
    await _insert_clip(owner_id, ClipStatus.PUBLISHED, published_at=now)  # not tagged

    _act_as(None)
    r = await client.get(f"/teams/{slug}/clips")
    assert r.status_code == 200, r.text
    assert [c["id"] for c in r.json()["items"]] == [tagged]
    assert r.json()["items"][0]["team"]["slug"] == slug
    assert (await client.get("/teams/no_such_team_xyz/clips")).status_code == 404


async def test_team_clips_hidden_while_forming(client):
    owner_sub, _, _ = await _new_user()
    _, _, a = await _new_user()
    _, _, b = await _new_user()
    slug = f"f{uuid.uuid4().hex[:10]}"
    _act_as(owner_sub)
    r = await client.post(
        "/teams",
        json={
            "name": "Forming",
            "slug": slug,
            "level": "beginner",
            "join_policy": "open",
            "invitee_usernames": [a, b],
        },
    )
    assert r.status_code == 201
    assert (await client.get(f"/teams/{slug}/clips")).status_code == 200
    _act_as(None)
    assert (await client.get(f"/teams/{slug}/clips")).status_code == 404


async def test_my_join_request_survives_a_reload(client):
    owner_sub, _, _ = await _new_user()
    slug = await _found_team(client, owner_sub, join_policy="request")
    me_sub, _, _ = await _new_user()
    _act_as(me_sub)

    r = await client.get(f"/teams/{slug}/join-requests/mine")
    assert r.status_code == 200, r.text
    assert r.json() == {"pending": False, "created_at": None}

    assert (await client.post(f"/teams/{slug}/join")).status_code == 201
    r = await client.get(f"/teams/{slug}/join-requests/mine")
    assert r.json()["pending"] is True
    assert r.json()["created_at"] is not None

    assert (await client.delete(f"/teams/{slug}/join")).status_code == 200
    assert (await client.get(f"/teams/{slug}/join-requests/mine")).json()["pending"] is False
