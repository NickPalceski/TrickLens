"""Integration tests for reports (F4): "Report a problem with this
analysis", "Report a bug", and reading them back with app/reports.py.

Real Postgres, only Cognito faked (same setup as test_listings.py).
"""

import json
import uuid
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from app import reports as reports_cli
from app.api import deps
from app.db import SessionLocal
from app.main import app
from app.models.clip import Analysis, Clip
from app.models.enums import ClipStatus, ReportKind
from app.models.report import Report
from app.models.user import User

pytestmark = pytest.mark.asyncio(loop_scope="session")

_CONTEXT = {
    "app_version": "test",
    "user_agent": "pytest",
    "viewport": "390×844",
    "theme": "dark",
    "api_mode": "live",
}


async def _new_user() -> tuple[str, uuid.UUID, str]:
    sub = f"test-{uuid.uuid4()}"
    username = f"u{uuid.uuid4().hex[:10]}"
    async with SessionLocal() as db:
        user = User(cognito_sub=sub, username=username)
        db.add(user)
        await db.commit()
        return sub, user.id, user.username


def _act_as(sub: str | None) -> None:
    app.dependency_overrides.clear()
    if sub is None:
        return

    async def _claims():
        return {"sub": sub, "email": f"{sub}@example.com"}

    async def _optional_user(db: deps.DbSession):
        return await db.scalar(select(User).where(User.cognito_sub == sub))

    app.dependency_overrides[deps.get_current_claims] = _claims
    app.dependency_overrides[deps.get_optional_user] = _optional_user


async def _clip(
    user_id: uuid.UUID, status: ClipStatus = ClipStatus.ANALYZED, *, analyzed: bool = True
) -> str:
    async with SessionLocal() as db:
        clip = Clip(
            user_id=user_id,
            s3_key=f"raw/{uuid.uuid4()}.mp4",
            processed_key="processed/x.mp4",
            status=status,
            analyze=analyzed,
            steeze_score=Decimal("72.5") if status == ClipStatus.ANALYZED and analyzed else None,
        )
        db.add(clip)
        await db.flush()
        if analyzed:
            db.add(
                Analysis(
                    clip_id=clip.id,
                    model_version="steeze-test",
                    confidence=Decimal("0.80"),
                    steeze_breakdown={"pop": 70.0},
                    details={"schema": 1, "tricks": [{"outcome": "landed", "confidence": 0.8}]},
                )
            )
        await db.commit()
        return str(clip.id)


async def _report(report_id: str) -> Report:
    async with SessionLocal() as db:
        report = await db.get(Report, uuid.UUID(report_id))
        assert report is not None
        return report


@pytest_asyncio.fixture(loop_scope="session")
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def test_analysis_report_snapshots_the_analysis_and_changes_nothing(client):
    sub, uid, _ = await _new_user()
    clip_id = await _clip(uid)
    _act_as(sub)

    resp = await client.post(
        f"/clips/{clip_id}/analysis-reports",
        json={
            "problems": ["score_off"],
            "trick_index": 0,
            "subscores": ["pop"],
            "score_direction": "too_high",
            "note": "Barely left the ground.",
            "share_video": False,
            "app_version": "test",
        },
    )
    assert resp.status_code == 201, resp.text
    report = await _report(resp.json()["id"])
    assert report.kind is ReportKind.ANALYSIS
    assert report.user_id == uid
    assert str(report.clip_id) == clip_id
    assert report.body["problems"] == ["score_off"]
    assert report.analysis["model_version"] == "steeze-test"
    assert report.analysis["steeze_score"] == "72.5"
    assert report.analysis["details"]["tricks"][0]["outcome"] == "landed"
    assert report.analysis["video_key"] is None, "no consent, so no video"

    clip = (await client.get(f"/clips/{clip_id}")).json()
    assert clip["status"] == "analyzed"
    assert clip["steeze_score"] == "72.5"


async def test_analysis_report_records_the_video_only_with_consent(client):
    sub, uid, _ = await _new_user()
    clip_id = await _clip(uid, ClipStatus.UNANALYZABLE)
    _act_as(sub)
    resp = await client.post(
        f"/clips/{clip_id}/analysis-reports",
        json={"problems": ["should_have_scored"], "share_video": True},
    )
    assert resp.status_code == 201, resp.text
    report = await _report(resp.json()["id"])
    assert report.share_video is True
    assert report.analysis["video_key"] == "processed/x.mp4"


async def test_analysis_report_rules(client):
    sub, uid, _ = await _new_user()
    other_sub, _, _ = await _new_user()
    clip_id = await _clip(uid)
    unanalyzed = await _clip(uid, analyzed=False)
    published = await _clip(uid, ClipStatus.PUBLISHED)
    url = f"/clips/{clip_id}/analysis-reports"

    _act_as(sub)
    assert (await client.post(url, json={})).status_code == 422, "says nothing"
    assert (await client.post(url, json={"note": "   "})).status_code == 422
    assert (await client.post(url, json={"note": "wrong", "trick_index": 1})).status_code == 422
    assert (await client.post(url, json={"problems": ["nope"]})).status_code == 422
    bad_sub = {"problems": ["score_off"], "subscores": ["vibes"]}
    assert (await client.post(url, json=bad_sub)).status_code == 422
    assert (await client.post(url, json={"note": "x", "extra": 1})).status_code == 422
    r = await client.post(f"/clips/{unanalyzed}/analysis-reports", json={"note": "x"})
    assert r.status_code == 409, "never analyzed"
    r = await client.post(f"/clips/{published}/analysis-reports", json={"note": "x"})
    assert r.status_code == 409

    _act_as(other_sub)
    assert (await client.post(url, json={"note": "x"})).status_code == 404, "not your clip"


async def test_bug_report_signed_in_or_out(client):
    sub, uid, _ = await _new_user()
    body = {"description": "  The login button spins forever.  ", "page": "/login"}

    _act_as(None)
    resp = await client.post("/bug-reports", json=body | {"context": _CONTEXT})
    assert resp.status_code == 201, resp.text
    anon = await _report(resp.json()["id"])
    assert anon.kind is ReportKind.BUG
    assert anon.user_id is None
    assert anon.body["description"] == "The login button spins forever."
    assert anon.body["context"]["viewport"] == "390×844"

    _act_as(sub)
    resp = await client.post("/bug-reports", json=body | {"context": _CONTEXT})
    assert (await _report(resp.json()["id"])).user_id == uid

    short = {"description": "broken", "context": _CONTEXT}
    assert (await client.post("/bug-reports", json=short)).status_code == 422
    huge = {"description": "x" * 4001, "context": _CONTEXT}
    assert (await client.post("/bug-reports", json=huge)).status_code == 422
    extra = body | {"context": _CONTEXT | {"cookies": "..."}}
    assert (await client.post("/bug-reports", json=extra)).status_code == 422


async def test_make_reports_reads_them_back(client, capsys):
    sub, uid, username = await _new_user()
    clip_id = await _clip(uid)
    _act_as(sub)
    resp = await client.post(
        f"/clips/{clip_id}/analysis-reports",
        json={"problems": ["missed_trick"], "note": "There were two.", "share_video": True},
    )
    report_id = resp.json()["id"]

    assert reports_cli.main(["--kind", "analysis", "--limit", "200"]) == 0
    listed = capsys.readouterr().out
    assert report_id in listed
    assert f"@{username}" in listed

    assert reports_cli.main(["--id", report_id]) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["user"] == username
    assert full["body"]["note"] == "There were two."
    assert full["analysis"]["video_key"] == "processed/x.mp4"
