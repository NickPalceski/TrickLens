"""Tests for /health/deep's schema-revision check.

Real Postgres and LocalStack, same as the other suites. The Cognito check
reaches the real dev pool, so these assert on the postgres check only rather
than the overall status.
"""

import httpx
import pytest

from app.api.routes import health
from app.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _deep() -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.get("/health/deep")


def _postgres(resp: httpx.Response) -> dict:
    return next(c for c in resp.json()["checks"] if c["name"] == "postgres")


async def test_deep_health_reports_migrated_revision():
    check = _postgres(await _deep())
    assert check["ok"] is True
    assert check["detail"]["revision"] == ",".join(sorted(health.expected_heads()))


async def test_deep_health_fails_when_schema_behind_code(monkeypatch):
    monkeypatch.setattr(health, "expected_heads", lambda: frozenset({"9999_not_applied"}))
    resp = await _deep()
    check = _postgres(resp)
    assert resp.status_code == 503
    assert check["ok"] is False
    assert "9999_not_applied" in check["error"]
