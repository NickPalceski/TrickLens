"""Integration tests for teams (step 4c): founding, roles, join policies,
the member cap, clip team-tagging/score-inclusion, and feed inclusion.

Same setup as test_social.py: real Postgres and LocalStack, only Cognito
faked.
"""

import uuid
from datetime import UTC, datetime
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

    async def _optional_user(db: deps.DbSession):
        return await db.scalar(select(User).where(User.cognito_sub == sub))

    app.dependency_overrides[deps.get_current_claims] = _claims
    app.dependency_overrides[deps.get_optional_user] = _optional_user


async def _insert_clip(
    user_id: uuid.UUID,
    status: ClipStatus,
    *,
    team_id: uuid.UUID | None = None,
    published_at: datetime | None = None,
) -> uuid.UUID:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=status,
            team_id=team_id,
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


_TEAM_BODY = {
    "level": "beginner",
    "join_policy": "open",
    "description": "test team",
}


async def _create_pending_team(
    client, owner_sub: str, invitee_names: list[str], *, join_policy: str = "open", slug: str = ""
) -> str:
    _act_as(owner_sub)
    slug = slug or f"team{uuid.uuid4().hex[:10]}"
    r = await client.post(
        "/teams",
        json={
            **_TEAM_BODY,
            "name": "Test Team",
            "slug": slug,
            "join_policy": join_policy,
            "invitee_usernames": invitee_names,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["founded"] is False
    return slug


async def _found_team(
    client, owner_sub: str, member_subs: list[str], *, join_policy: str = "open"
) -> tuple[str, list[str]]:
    """Creates a team and accepts every founding invite, returning the
    founded team's slug plus the invitees' usernames."""
    names = []
    for sub in member_subs:
        _, _, name = await _new_user_from_sub(sub)
        names.append(name)
    slug = await _create_pending_team(client, owner_sub, names, join_policy=join_policy)
    for sub in member_subs:
        _act_as(sub)
        r = await client.post(f"/teams/{slug}/invites/mine/accept")
        assert r.status_code == 200, r.text
    return slug, names


async def _new_user_from_sub(sub: str) -> tuple[str, uuid.UUID, str]:
    async with SessionLocal() as db:
        user = await db.scalar(select(User).where(User.cognito_sub == sub))
        return sub, user.id, user.username


async def test_team_founding_completes_when_all_invites_accepted(client):
    owner_sub, owner_id, owner_name = await _new_user()
    m1_sub, m1_id, m1_name = await _new_user()
    m2_sub, m2_id, m2_name = await _new_user()

    slug = await _create_pending_team(client, owner_sub, [m1_name, m2_name])

    # Outsider can't see a still-forming team.
    outsider_sub, _, _ = await _new_user()
    _act_as(outsider_sub)
    r = await client.get(f"/teams/{slug}")
    assert r.status_code == 404

    # An invitee can see it and sees the other invitee as still pending.
    _act_as(m1_sub)
    r = await client.get(f"/teams/{slug}")
    assert r.status_code == 200
    assert r.json()["founded"] is False
    assert {u["username"] for u in r.json()["pending_founders"]} == {m1_name, m2_name}

    r = await client.post(f"/teams/{slug}/invites/mine/accept")
    assert r.status_code == 200
    assert r.json()["founded"] is False  # m2 hasn't accepted yet

    _act_as(m2_sub)
    r = await client.post(f"/teams/{slug}/invites/mine/accept")
    assert r.status_code == 200
    assert r.json()["founded"] is True
    assert r.json()["member_count"] == 3

    # Now visible to anyone.
    _act_as(outsider_sub)
    r = await client.get(f"/teams/{slug}")
    assert r.status_code == 200
    assert r.json()["owner"]["username"] == owner_name


async def test_rejecting_a_founding_invite_cancels_the_whole_team(client):
    owner_sub, _, _ = await _new_user()
    m1_sub, _, m1_name = await _new_user()
    m2_sub, _, m2_name = await _new_user()

    slug = f"team{uuid.uuid4().hex[:10]}"
    await _create_pending_team(client, owner_sub, [m1_name, m2_name], slug=slug)

    _act_as(m1_sub)
    r = await client.post(f"/teams/{slug}/invites/mine/accept")
    assert r.status_code == 200

    _act_as(m2_sub)
    r = await client.post(f"/teams/{slug}/invites/mine/reject")
    assert r.status_code == 204

    # Gone for everyone, including the invitee who already accepted.
    for sub in (owner_sub, m1_sub, m2_sub):
        _act_as(sub)
        r = await client.get(f"/teams/{slug}")
        assert r.status_code == 404

    # Slug is free again — redoing it from scratch, with the same slug, works.
    slug2 = await _create_pending_team(client, owner_sub, [m1_name, m2_name], slug=slug)
    assert slug2 == slug


async def test_owner_can_cancel_pending_team(client):
    owner_sub, _, _ = await _new_user()
    _, _, m1_name = await _new_user()
    _, _, m2_name = await _new_user()

    slug = await _create_pending_team(client, owner_sub, [m1_name, m2_name])
    _act_as(owner_sub)
    r = await client.delete(f"/teams/{slug}")
    assert r.status_code == 204

    r = await client.get(f"/teams/{slug}")
    assert r.status_code == 404


async def test_creation_requires_at_least_two_invitees(client):
    owner_sub, _, _ = await _new_user()
    _, _, only_name = await _new_user()
    _act_as(owner_sub)
    r = await client.post(
        "/teams",
        json={
            **_TEAM_BODY,
            "name": "Solo",
            "slug": f"team{uuid.uuid4().hex[:10]}",
            "invitee_usernames": [only_name],
        },
    )
    assert r.status_code == 422


async def test_join_policy_open_lets_anyone_join(client):
    owner_sub, _, _ = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub], join_policy="open")

    joiner_sub, _, _ = await _new_user()
    _act_as(joiner_sub)
    r = await client.post(f"/teams/{slug}/join")
    assert r.status_code == 201
    assert r.json()["member_count"] == 4


async def test_join_policy_request_needs_admin_approval(client):
    owner_sub, _, _ = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub], join_policy="request")

    requester_sub, _, requester_name = await _new_user()
    _act_as(requester_sub)
    r = await client.post(f"/teams/{slug}/join")
    assert r.status_code == 201
    assert r.json()["member_count"] == 3  # not a member yet, just requested

    _act_as(owner_sub)
    r = await client.get(f"/teams/{slug}/join-requests")
    assert r.status_code == 200
    assert [u["user"]["username"] for u in r.json()] == [requester_name]

    r = await client.post(f"/teams/{slug}/join-requests/{requester_name}/accept")
    assert r.status_code == 200
    assert r.json()["role"] == "member"

    _act_as(requester_sub)
    r = await client.get(f"/teams/{slug}")
    assert r.json()["member_count"] == 4
    assert r.json()["my_role"] == "member"


async def test_join_policy_invite_only_blocks_self_join(client):
    owner_sub, _, _ = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub], join_policy="invite_only")

    outsider_sub, _, outsider_name = await _new_user()
    _act_as(outsider_sub)
    r = await client.post(f"/teams/{slug}/join")
    assert r.status_code == 403

    _act_as(owner_sub)
    r = await client.post(f"/teams/{slug}/invites", json={"username": outsider_name})
    assert r.status_code == 204

    _act_as(outsider_sub)
    r = await client.post(f"/teams/{slug}/invites/mine/accept")
    assert r.status_code == 200
    assert r.json()["member_count"] == 4


async def test_admin_can_kick_member_but_not_admin_or_owner(client):
    owner_sub, _, owner_name = await _new_user()
    admin1_sub, _, admin1_name = await _new_user()
    admin2_sub, _, admin2_name = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [admin1_sub, admin2_sub])

    member_sub, _, member_name = await _new_user()
    _act_as(member_sub)
    r = await client.post(f"/teams/{slug}/join")
    assert r.status_code == 201

    _act_as(owner_sub)
    for name in (admin1_name, admin2_name):
        r = await client.patch(f"/teams/{slug}/members/{name}", json={"role": "admin"})
        assert r.status_code == 200

    _act_as(admin1_sub)
    r = await client.delete(f"/teams/{slug}/members/{member_name}")
    assert r.status_code == 204

    r = await client.delete(f"/teams/{slug}/members/{admin2_name}")
    assert r.status_code == 403  # admins can't kick other admins

    r = await client.delete(f"/teams/{slug}/members/{owner_name}")
    assert r.status_code == 409  # owner can't be removed at all

    _act_as(owner_sub)
    r = await client.patch(f"/teams/{slug}/members/{owner_name}", json={"role": "owner"})
    assert r.status_code == 422  # ownership can't be handed off this way


async def test_member_cap_enforced(client):
    owner_sub, _, _ = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub], join_policy="open")

    # 3 members so far; fill up to the 20 cap.
    for _ in range(17):
        sub, _, _ = await _new_user()
        _act_as(sub)
        r = await client.post(f"/teams/{slug}/join")
        assert r.status_code == 201

    _act_as(owner_sub)
    r = await client.get(f"/teams/{slug}")
    assert r.json()["member_count"] == 20

    overflow_sub, _, _ = await _new_user()
    _act_as(overflow_sub)
    r = await client.post(f"/teams/{slug}/join")
    assert r.status_code == 409


async def test_clip_team_tag_requires_membership_and_analyzed_status(client):
    owner_sub, owner_id, _ = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub])

    _act_as(owner_sub)
    team_id = (await client.get(f"/teams/{slug}")).json()["id"]

    draft_id = await _insert_clip(owner_id, ClipStatus.DRAFT)
    r = await client.patch(f"/clips/{draft_id}/team", json={"team_id": team_id})
    assert r.status_code == 409

    analyzed_id = await _insert_clip(owner_id, ClipStatus.ANALYZED)
    r = await client.patch(f"/clips/{analyzed_id}/team", json={"team_id": team_id})
    assert r.status_code == 200
    assert r.json()["team"]["slug"] == slug

    # Re-fetch through a brand-new request/session, not just the PATCH
    # response: a `viewonly` relationship would let `clip.team = team`
    # populate the in-memory object (so the line above would still pass)
    # while silently never persisting it, which only a fresh read exposes.
    r = await client.get(f"/clips/{analyzed_id}")
    assert r.json()["team"]["slug"] == slug

    outsider_sub, outsider_id, _ = await _new_user()
    _act_as(outsider_sub)
    outsider_clip_id = await _insert_clip(outsider_id, ClipStatus.ANALYZED)
    r = await client.patch(f"/clips/{outsider_clip_id}/team", json={"team_id": team_id})
    assert r.status_code == 403  # not a member of that team


async def test_score_inclusion_editable_after_publish(client):
    sub, user_id, _ = await _new_user()
    _act_as(sub)
    clip_id = await _insert_clip(user_id, ClipStatus.PUBLISHED, published_at=datetime.now(UTC))

    r = await client.patch(f"/clips/{clip_id}/score-inclusion", json={"included": False})
    assert r.status_code == 200
    assert r.json()["score_included"] is False

    # Stays editable indefinitely, unlike team tagging.
    r = await client.patch(f"/clips/{clip_id}/score-inclusion", json={"included": True})
    assert r.status_code == 200
    assert r.json()["score_included"] is True

    draft_id = await _insert_clip(user_id, ClipStatus.DRAFT)
    r = await client.patch(f"/clips/{draft_id}/score-inclusion", json={"included": False})
    assert r.status_code == 409


async def test_feed_includes_team_clip_without_duplicating_followed_author(client):
    viewer_sub, _, _ = await _new_user()
    owner_sub, owner_id, owner_name = await _new_user()
    m1_sub, _, _ = await _new_user()
    m2_sub, _, _ = await _new_user()
    slug, _ = await _found_team(client, owner_sub, [m1_sub, m2_sub])
    team_id = (await _found_team_out(client, owner_sub, slug))["id"]

    now = datetime.now(UTC)
    clip_id = await _insert_clip(owner_id, ClipStatus.PUBLISHED, team_id=team_id, published_at=now)

    _act_as(viewer_sub)
    await client.post(f"/users/{owner_name}/follow")
    await client.post(f"/teams/{slug}/follow")

    r = await client.get("/feed")
    assert r.status_code == 200
    # Followed both the author and the team the clip is tagged to — must
    # appear exactly once, not twice.
    assert [item["id"] for item in r.json()["items"]] == [str(clip_id)]


async def _found_team_out(client, sub: str, slug: str) -> dict:
    _act_as(sub)
    r = await client.get(f"/teams/{slug}")
    return r.json()
