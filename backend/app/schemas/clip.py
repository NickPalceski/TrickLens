"""Clip, analysis, and trick API schemas.

Split by direction on purpose, same as schemas/user.py: ORM objects are
never returned from a route.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ClipStatus


class ClipCreate(BaseModel):
    """Body for POST /clips. duration_ms/source_fps are read off the
    browser's <video> element — best-effort until step 6 can verify them
    server-side with ffprobe."""

    content_type: str
    duration_ms: int = Field(gt=0, le=30_000)  # clips are capped at 30s
    source_fps: int = Field(gt=0, le=240)


class TrickOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_name: str


class AnalysisOut(BaseModel):
    # protected_namespaces=(): "model_version" collides with pydantic's
    # reserved "model_" prefix otherwise, and it's the right field name here.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    model_version: str
    confidence: Decimal
    steeze_breakdown: dict[str, float] | None = None
    failure_reason: str | None = None
    created_at: datetime


class ClipOut(BaseModel):
    id: uuid.UUID
    status: ClipStatus
    video_url: str  # presigned at response time — never the raw key
    duration_ms: int | None = None
    source_fps: int | None = None
    steeze_score: Decimal | None = None
    published_at: datetime | None = None
    tricks: list[TrickOut] = []
    analysis: AnalysisOut | None = None
    created_at: datetime


class ClipCreateOut(BaseModel):
    """POST /clips returns the row plus the one-time presigned upload URL,
    together, so the client doesn't need a second round trip."""

    clip: ClipOut
    upload_url: str


class TagTricksRequest(BaseModel):
    """Body for POST /clips/{id}/tricks. Plain names for now — get-or-create
    against `tricks`, no fuzzy/alias matching yet (see docs/ARCHITECTURE.md
    §5's design notes)."""

    tricks: list[str] = Field(min_length=1, max_length=5)

    @field_validator("tricks")
    @classmethod
    def _validate_tricks(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v]
        if any(not (1 <= len(t) <= 60) for t in cleaned):
            raise ValueError("each trick name must be 1-60 characters")
        return cleaned
