"""Integration tests for Discover (4d): view tracking, personal/team average
scores, the clip rankings rebuild (score vs. engagement sort, the 7-day
window), and the team score-increase ranking.

Same setup as test_teams.py: real Postgres and LocalStack, only Cognito
faked. app/rankings.py's run() is awaited directly rather than shelling out
to `make rankings` — same job, no subprocess needed in-process.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app import rankings
from app.api import deps
from app.db import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.discover import TeamScoreHistory
from app.models.enums import ClipStatus, JoinPolicy, TeamLevel
from app.models.social import ClipView, Comment, Like
from app.models.team import Team
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
    *,
    steeze_score: Decimal = Decimal("70.0"),
    score_included: bool = True,
    team_id: uuid.UUID | None = None,
    published_at: datetime | None = None,
) -> uuid.UUID:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=ClipStatus.PUBLISHED,
            steeze_score=steeze_score,
            score_included=score_included,
            team_id=team_id,
            published_at=published_at or datetime.now(UTC),
        )
        db.add(clip)
        await db.commit()
        return clip.id


async def _insert_team(owner_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    """Bypasses the founding-invite flow (already covered by test_teams.py)
    — a directly-inserted, already-founded team is all these tests need."""
    async with SessionLocal() as db:
        team = Team(
            name="Test Team",
            slug=f"team{uuid.uuid4().hex[:10]}",
            level=TeamLevel.INTERMEDIATE,
            join_policy=JoinPolicy.OPEN,
            owner_id=owner_id,
            founded_at=datetime.now(UTC),
        )
        db.add(team)
        await db.commit()
        return team.id, team.slug


async def _insert_score_snapshot(
    team_id: uuid.UUID, score: Decimal | None, captured_at: datetime
) -> None:
    async with SessionLocal() as db:
        db.add(TeamScoreHistory(team_id=team_id, score=score, captured_at=captured_at))
        await db.commit()


async def _insert_like(user_id: uuid.UUID, clip_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        db.add(Like(user_id=user_id, clip_id=clip_id))
        await db.commit()


async def _insert_comment(user_id: uuid.UUID, clip_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        db.add(Comment(clip_id=clip_id, user_id=user_id, body="nice"))
        await db.commit()


async def _insert_view(user_id: uuid.UUID, clip_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        db.add(ClipView(clip_id=clip_id, user_id=user_id))
        await db.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def _all_discover_clip_ids(client, sort: str) -> list[str]:
    """This dev database accumulates real clips across every manual
    verification session (200+ and counting) — `/discover/clips` ranks
    globally, unlike the home feed's per-follower scoping, so a test clip
    is never guaranteed to land on page 1. Walk every page instead of
    assuming one, and assert presence/relative order against the full list
    rather than an exact page of results."""
    ids: list[str] = []
    offset = 0
    while True:
        params = {"sort": sort, "limit": 50, "offset": offset}
        r = await client.get("/discover/clips", params=params)
        page = r.json()
        ids += [item["id"] for item in page["items"]]
        if page["next_offset"] is None:
            return ids
        offset = page["next_offset"]


async def test_view_recording_self_excluded_others_not_deduped(client):
    owner_sub, owner_id, _ = await _new_user()
    viewer_sub, _, _ = await _new_user()
    clip_id = await _insert_clip(owner_id)

    _act_as(owner_sub)
    r = await client.post(f"/clips/{clip_id}/view")
    assert r.status_code == 201
    assert r.json()["view_count"] == 0  # self-views don't count

    _act_as(viewer_sub)
    r = await client.post(f"/clips/{clip_id}/view")
    assert r.json()["view_count"] == 1
    r = await client.post(f"/clips/{clip_id}/view")  # a rewatch counts again
    assert r.json()["view_count"] == 2


async def test_user_average_score_excludes_toggled_off_clips(client):
    sub, user_id, username = await _new_user()
    _act_as(sub)

    r = await client.get(f"/users/{username}")
    assert r.json()["average_score"] is None  # no published clips yet

    clip_a = await _insert_clip(user_id, steeze_score=Decimal("60.0"))
    await _insert_clip(user_id, steeze_score=Decimal("80.0"))
    r = await client.get(f"/users/{username}")
    assert Decimal(r.json()["average_score"]) == Decimal("70.0")

    r = await client.patch(f"/clips/{clip_a}/score-inclusion", json={"included": False})
    assert r.status_code == 200
    r = await client.get(f"/users/{username}")
    assert Decimal(r.json()["average_score"]) == Decimal("80.0")


async def test_team_average_score_caps_at_top_10(client):
    owner_sub, owner_id, _ = await _new_user()
    team_id, slug = await _insert_team(owner_id)

    # Scores 51..61 (11 clips) — the top 10 are 52..61, excluding the lowest.
    for score in range(51, 62):
        await _insert_clip(owner_id, steeze_score=Decimal(str(score)), team_id=team_id)

    _act_as(owner_sub)
    r = await client.get(f"/teams/{slug}")
    assert Decimal(r.json()["average_score"]) == Decimal("56.5")


async def test_discover_clips_score_sort_excludes_score_excluded(client):
    sub, user_id, _ = await _new_user()
    high = await _insert_clip(user_id, steeze_score=Decimal("90.0"))
    excluded = await _insert_clip(user_id, steeze_score=Decimal("80.0"), score_included=False)
    low = await _insert_clip(user_id, steeze_score=Decimal("70.0"))

    await rankings.run()

    _act_as(sub)
    ids = await _all_discover_clip_ids(client, sort="score")
    assert ids.index(str(high)) < ids.index(str(low))
    assert str(excluded) not in ids


async def test_discover_clips_engagement_sort_blends_weights(client):
    sub, user_id, _ = await _new_user()
    viewer_sub, viewer_id, _ = await _new_user()
    # A: 10 views, 1 like, 0 comments -> 10*1 + 1*5 + 0*10 = 15
    clip_a = await _insert_clip(user_id)
    for _ in range(10):
        await _insert_view(viewer_id, clip_a)
    await _insert_like(viewer_id, clip_a)
    # B: 0 views, 0 likes, 2 comments -> 0 + 0 + 2*10 = 20
    clip_b = await _insert_clip(user_id)
    await _insert_comment(viewer_id, clip_b)
    await _insert_comment(viewer_id, clip_b)

    await rankings.run()

    _act_as(sub)
    ids = await _all_discover_clip_ids(client, sort="engagement")
    assert ids.index(str(clip_b)) < ids.index(str(clip_a))


async def test_discover_clips_window_excludes_old_clips(client):
    sub, user_id, _ = await _new_user()
    old = await _insert_clip(
        user_id, steeze_score=Decimal("99.0"), published_at=datetime.now(UTC) - timedelta(days=10)
    )
    recent = await _insert_clip(user_id, steeze_score=Decimal("40.0"))

    await rankings.run()

    _act_as(sub)
    ids = await _all_discover_clip_ids(client, sort="score")
    assert str(recent) in ids
    assert str(old) not in ids


async def test_discover_teams_ranked_by_increase_new_team_excluded(client):
    viewer_sub, _, _ = await _new_user()
    _, owner_a, _ = await _new_user()
    _, owner_b, _ = await _new_user()
    _, owner_c, _ = await _new_user()
    team_a, _ = await _insert_team(owner_a)
    team_b, _ = await _insert_team(owner_b)
    team_c, _ = await _insert_team(owner_c)  # no history from a week ago

    now = datetime.now(UTC)
    week_ago = now - timedelta(days=8)
    await _insert_score_snapshot(team_a, Decimal("50.0"), week_ago)
    await _insert_score_snapshot(team_a, Decimal("70.0"), now)  # +20
    await _insert_score_snapshot(team_b, Decimal("60.0"), week_ago)
    await _insert_score_snapshot(team_b, Decimal("65.0"), now)  # +5
    await _insert_score_snapshot(team_c, Decimal("90.0"), now)  # only ever one snapshot

    _act_as(viewer_sub)
    # Walk every page — this dev database accumulates real teams across every
    # manual verification session (including ones with their own backdated
    # history from hand-testing this very ranking), so team_a/team_b aren't
    # guaranteed to be the only — or the first — qualifying teams.
    items: list[dict] = []
    offset = 0
    while True:
        r = await client.get("/discover/teams", params={"limit": 50, "offset": offset})
        page = r.json()
        items += page["items"]
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]

    team_ids = [item["team"]["id"] for item in items]
    by_id = {item["team"]["id"]: item for item in items}
    assert str(team_c) not in team_ids  # no baseline -> excluded
    assert team_ids.index(str(team_a)) < team_ids.index(str(team_b))  # +20 outranks +5
    assert Decimal(by_id[str(team_a)]["score_delta"]) == Decimal("20.0")
    assert Decimal(by_id[str(team_b)]["score_delta"]) == Decimal("5.0")
