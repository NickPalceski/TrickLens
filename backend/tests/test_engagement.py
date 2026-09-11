"""Integration tests for likes and comments (step 4b).

Same setup as test_social.py: real Postgres and LocalStack, only Cognito
faked. Clips are inserted directly rather than driven through the whole
upload pipeline — that path is already covered by test_clips.py, and these
tests only care about like/comment behaviour on top of a clip that's already
in some status.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio

from app.api import deps
from app.db import SessionLocal
from app.main import app
from app.models.clip import Clip
from app.models.enums import ClipStatus
from app.models.social import Comment
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

    app.dependency_overrides[deps.get_current_claims] = _claims


async def _make_clip(user_id: uuid.UUID, status: ClipStatus, **overrides) -> uuid.UUID:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            status=status,
            published_at=datetime.now(UTC) if status == ClipStatus.PUBLISHED else None,
            steeze_score=Decimal("70.0") if status == ClipStatus.PUBLISHED else None,
            **overrides,
        )
        db.add(clip)
        await db.commit()
        return clip.id


async def _add_comment(
    clip_id: uuid.UUID, user_id: uuid.UUID, body: str, created_at: datetime, parent_id=None
) -> uuid.UUID:
    """Sets created_at explicitly, same reason test_social.py's
    _publish_clip sets published_at explicitly rather than relying on
    server_default now() — a single transaction sees one now() value for
    its whole duration, so rows inserted together wouldn't otherwise sort
    distinctly."""
    async with SessionLocal() as db:
        comment = Comment(
            clip_id=clip_id, user_id=user_id, body=body, created_at=created_at, parent_id=parent_id
        )
        db.add(comment)
        await db.commit()
        return comment.id


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------- likes ---


async def test_like_unlike_roundtrip(client):
    liker_sub, _, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(liker_sub)
    r = await client.post(f"/clips/{clip_id}/like")
    assert r.status_code == 201, r.text
    assert r.json()["like_count"] == 1
    assert r.json()["liked_by_me"] is True

    r = await client.post(f"/clips/{clip_id}/like")
    assert r.status_code == 409

    r = await client.get(f"/clips/{clip_id}")
    assert r.json()["like_count"] == 1
    assert r.json()["liked_by_me"] is True

    r = await client.delete(f"/clips/{clip_id}/like")
    assert r.status_code == 200
    assert r.json()["like_count"] == 0
    assert r.json()["liked_by_me"] is False

    # Idempotent — unliking again is a no-op 200, not an error.
    r = await client.delete(f"/clips/{clip_id}/like")
    assert r.status_code == 200


async def test_can_like_own_clip(client):
    """Unlike following yourself (blocked), liking your own clip is normal
    and harmless — no self-like restriction."""
    sub, user_id, _ = await _new_user()
    clip_id = await _make_clip(user_id, ClipStatus.PUBLISHED)

    _act_as(sub)
    r = await client.post(f"/clips/{clip_id}/like")
    assert r.status_code == 201, r.text
    assert r.json()["liked_by_me"] is True


async def test_liking_someone_elses_draft_is_invisible(client):
    stranger_sub, _, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.DRAFT)

    _act_as(stranger_sub)
    r = await client.post(f"/clips/{clip_id}/like")
    assert r.status_code == 404


async def test_liking_own_draft_conflicts(client):
    """Visible to its owner (unlike a stranger's draft), but not likeable
    until published — the clip exists, so this is 409, not 404."""
    sub, user_id, _ = await _new_user()
    clip_id = await _make_clip(user_id, ClipStatus.DRAFT)

    _act_as(sub)
    r = await client.post(f"/clips/{clip_id}/like")
    assert r.status_code == 409


# ------------------------------------------------------------- comments ---


async def test_add_and_list_top_level_comment(client):
    commenter_sub, commenter_id, commenter_name = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(commenter_sub)
    r = await client.post(f"/clips/{clip_id}/comments", json={"body": "clean landing"})
    assert r.status_code == 201, r.text
    assert r.json()["body"] == "clean landing"
    assert r.json()["author"]["username"] == commenter_name
    assert r.json()["replies"] == []
    comment_id = r.json()["id"]

    r = await client.get(f"/clips/{clip_id}")
    assert r.json()["comment_count"] == 1

    r = await client.get(f"/clips/{clip_id}/comments")
    assert r.status_code == 200
    assert [i["id"] for i in r.json()["items"]] == [comment_id]


async def test_reply_nests_under_top_level_comment(client):
    a_sub, a_id, _ = await _new_user()
    b_sub, b_id, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(a_sub)
    top = await client.post(f"/clips/{clip_id}/comments", json={"body": "nice one"})
    top_id = top.json()["id"]

    _act_as(b_sub)
    reply = await client.post(
        f"/clips/{clip_id}/comments", json={"body": "agreed", "parent_id": top_id}
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["parent_id"] == top_id

    r = await client.get(f"/clips/{clip_id}/comments")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == top_id
    assert [rep["body"] for rep in items[0]["replies"]] == ["agreed"]

    r = await client.get(f"/clips/{clip_id}")
    assert r.json()["comment_count"] == 2  # counts replies too


async def test_cannot_reply_to_a_reply(client):
    a_sub, _, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(a_sub)
    top = await client.post(f"/clips/{clip_id}/comments", json={"body": "top"})
    top_id = top.json()["id"]
    reply = await client.post(
        f"/clips/{clip_id}/comments", json={"body": "reply", "parent_id": top_id}
    )
    reply_id = reply.json()["id"]

    r = await client.post(
        f"/clips/{clip_id}/comments", json={"body": "reply to a reply", "parent_id": reply_id}
    )
    assert r.status_code == 422


async def test_parent_from_a_different_clip_is_rejected(client):
    a_sub, _, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_a = await _make_clip(owner_id, ClipStatus.PUBLISHED)
    clip_b = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(a_sub)
    top = await client.post(f"/clips/{clip_a}/comments", json={"body": "on clip a"})
    top_id = top.json()["id"]

    r = await client.post(f"/clips/{clip_b}/comments", json={"body": "reply", "parent_id": top_id})
    assert r.status_code == 404


async def test_commenting_on_a_draft_matches_like_rules(client):
    stranger_sub, _, _ = await _new_user()
    owner_sub, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.DRAFT)

    _act_as(stranger_sub)
    r = await client.post(f"/clips/{clip_id}/comments", json={"body": "hi"})
    assert r.status_code == 404

    _act_as(owner_sub)
    r = await client.post(f"/clips/{clip_id}/comments", json={"body": "hi"})
    assert r.status_code == 409


async def test_delete_comment_permissions(client):
    author_sub, author_id, _ = await _new_user()
    owner_sub, owner_id, _ = await _new_user()
    stranger_sub, _, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(author_sub)
    r = await client.post(f"/clips/{clip_id}/comments", json={"body": "delete me"})
    comment_id = r.json()["id"]

    # A third party can't delete someone else's comment.
    _act_as(stranger_sub)
    r = await client.delete(f"/clips/{clip_id}/comments/{comment_id}")
    assert r.status_code == 403

    # The clip owner can, even though they didn't write it (moderation).
    _act_as(owner_sub)
    r = await client.delete(f"/clips/{clip_id}/comments/{comment_id}")
    assert r.status_code == 204

    r = await client.get(f"/clips/{clip_id}/comments")
    assert r.json()["items"] == []

    # Already gone.
    r = await client.delete(f"/clips/{clip_id}/comments/{comment_id}")
    assert r.status_code == 404


async def test_delete_own_comment_and_cascade_to_replies(client):
    author_sub, author_id, _ = await _new_user()
    replier_sub, _, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    _act_as(author_sub)
    top = await client.post(f"/clips/{clip_id}/comments", json={"body": "top"})
    top_id = top.json()["id"]

    _act_as(replier_sub)
    await client.post(f"/clips/{clip_id}/comments", json={"body": "reply", "parent_id": top_id})

    # The author deletes their own top-level comment.
    _act_as(author_sub)
    r = await client.delete(f"/clips/{clip_id}/comments/{top_id}")
    assert r.status_code == 204

    r = await client.get(f"/clips/{clip_id}")
    assert r.json()["comment_count"] == 0  # the reply cascaded away too


async def test_comment_list_keyset_pagination(client):
    viewer_sub, _, _ = await _new_user()
    _, commenter_id, _ = await _new_user()
    _, owner_id, _ = await _new_user()
    clip_id = await _make_clip(owner_id, ClipStatus.PUBLISHED)

    now = datetime.now(UTC)
    made = [
        await _add_comment(clip_id, commenter_id, f"c{i}", now - timedelta(minutes=i))
        for i in range(3)
    ]

    _act_as(viewer_sub)
    r = await client.get(f"/clips/{clip_id}/comments", params={"limit": 2})
    page1 = r.json()
    assert [i["id"] for i in page1["items"]] == [str(made[0]), str(made[1])]
    assert page1["next_cursor"] is not None

    r = await client.get(
        f"/clips/{clip_id}/comments", params={"limit": 2, "cursor": page1["next_cursor"]}
    )
    page2 = r.json()
    assert [i["id"] for i in page2["items"]] == [str(made[2])]
    assert page2["next_cursor"] is None
