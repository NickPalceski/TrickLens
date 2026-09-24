"""Health endpoints.

Two on purpose:

  /health       - no dependencies. What load balancers and uptime checks hit.
                  Must stay fast and must never fail because Postgres blipped.
  /health/deep  - actually round-trips every dependency. This is the
                  acceptance test for local setup and the first thing to
                  check when something is wrong. Its postgres check also
                  fails if the schema isn't at this image's Alembic head, so
                  the deploy pipeline's smoke test catches an unmigrated DB.
"""

import asyncio
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from alembic.script import ScriptDirectory
from app.api.deps import DbSession
from app.config import get_settings
from app.services import auth
from app.services.queue import get_queue
from app.services.storage import get_storage

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "env": get_settings().env}


async def _timed(name: str, coro) -> dict[str, Any]:
    """Run one dependency check, capturing latency and any failure."""
    started = time.perf_counter()
    try:
        detail = await asyncio.wait_for(coro, timeout=5.0)
        return {
            "name": name,
            "ok": True,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            **({"detail": detail} if detail else {}),
        }
    except Exception as exc:
        return {
            "name": name,
            "ok": False,
            "ms": round((time.perf_counter() - started) * 1000, 1),
            # Type + message: enough to diagnose, no stack trace leaked.
            "error": f"{type(exc).__name__}: {exc}",
        }


# backend/alembic/, which the Dockerfile copies into the image next to app/.
_ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "alembic"


@lru_cache
def expected_heads() -> frozenset[str]:
    """The revision(s) this build's code expects. Parsed from disk once per container."""
    return frozenset(ScriptDirectory(str(_ALEMBIC_DIR)).get_heads())


async def _check_db(db: AsyncSession) -> dict[str, str]:
    # Sequential on purpose: the checks share one AsyncSession, which can't
    # run two statements concurrently.
    await db.execute(text("SELECT 1"))
    # Fails with UndefinedTable on a never-migrated DB — also a failure.
    rows = await db.execute(text("SELECT version_num FROM alembic_version"))
    current = frozenset(rows.scalars())
    expected = expected_heads()
    if current != expected:
        raise RuntimeError(
            f"schema at revision {sorted(current) or 'none'}, code expects {sorted(expected)}"
        )
    return {"revision": ",".join(sorted(current))}


@router.get("/health/deep")
async def health_deep(db: DbSession, response: Response) -> dict[str, Any]:
    """Verify Postgres, S3 and SQS are all genuinely reachable."""
    checks = await asyncio.gather(
        _timed("postgres", _check_db(db)),
        _timed("s3", get_storage().check()),
        _timed("sqs", get_queue().depth()),
        _timed("cognito", auth.check()),
    )

    healthy = all(c["ok"] for c in checks)
    if not healthy:
        response.status_code = 503

    return {
        "status": "ok" if healthy else "degraded",
        "env": get_settings().env,
        "checks": checks,
    }
