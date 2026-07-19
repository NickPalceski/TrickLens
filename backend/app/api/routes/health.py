"""Health endpoints.

Two on purpose:

  /health       - no dependencies. What load balancers and uptime checks hit.
                  Must stay fast and must never fail because Postgres blipped.
  /health/deep  - actually round-trips every dependency. This is the
                  acceptance test for local setup and the first thing to
                  check when something is wrong.
"""

import asyncio
import time
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession
from app.config import get_settings
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


async def _check_db(db: AsyncSession) -> None:
    await db.execute(text("SELECT 1"))


@router.get("/health/deep")
async def health_deep(db: DbSession, response: Response) -> dict[str, Any]:
    """Verify Postgres, S3 and SQS are all genuinely reachable."""
    checks = await asyncio.gather(
        _timed("postgres", _check_db(db)),
        _timed("s3", get_storage().check()),
        _timed("sqs", get_queue().depth()),
    )

    healthy = all(c["ok"] for c in checks)
    if not healthy:
        response.status_code = 503

    return {
        "status": "ok" if healthy else "degraded",
        "env": get_settings().env,
        "checks": checks,
    }
