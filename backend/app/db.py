"""Database engine and session management."""

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    # Neon (and any serverless Postgres) drops idle connections. Without
    # pre-ping the first query after an idle period fails with a stale
    # connection error.
    pool_pre_ping=True,
    # Lambda containers are frozen between invocations, so a large pool is
    # wasted memory and wasted Postgres connection slots.
    pool_size=5,
    max_overflow=5,
    echo=False,
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

T = TypeVar("T")


def run_in_fresh_loop(main: Callable[[], Awaitable[T]]) -> T:
    """asyncio.run(main()) for a Lambda handler, then close the pool's
    connections before that event loop closes.

    The worker and rankings handlers call asyncio.run once per invocation,
    so every invocation gets a new loop. `engine` is module-level and
    outlives it in a warm container, and an asyncpg connection only works
    on the loop that opened it. Left in the pool, the next invocation
    checks it out and dies with "attached to a different loop" before doing
    anything (the 6c-2 prod check: a clip stuck `queued`). Disposing here
    means each invocation opens its own connection, which costs one Neon
    connect, nothing next to an analysis. The API is unaffected: Mangum
    keeps one loop for the container's life. See docs/components/services.md,
    Database sessions.
    """

    async def _run() -> T:
        try:
            return await main()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, committed on success."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
