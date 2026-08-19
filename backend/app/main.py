"""FastAPI application assembly."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import health, users
from app.config import get_settings
from app.db import engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
)
log = logging.getLogger("tricklens")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting tricklens api (env=%s)", settings.env)
    yield
    # Lambda freezes containers rather than stopping them, so this rarely
    # runs in production. It matters locally, where reload restarts the app
    # constantly and would otherwise leak Postgres connections.
    await engine.dispose()
    log.info("shutdown complete")


app = FastAPI(
    title="TrickLens API",
    version="0.1.0",
    description="Skate clip sharing with automated execution scoring.",
    lifespan=lifespan,
    # Interactive docs are a dev convenience, not something to expose publicly.
    docs_url="/docs" if settings.is_dev else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Uniform error shape, and never leak internals to the client.

    The full traceback goes to logs (CloudWatch in production); the caller
    gets a generic message.
    """
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


app.include_router(health.router)
app.include_router(users.router)
