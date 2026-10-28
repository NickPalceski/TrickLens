"""Clip, analysis, and trick API schemas.

Split by direction on purpose, same as schemas/user.py: ORM objects are
never returned from a route.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import ClipStatus
from app.schemas.team import TeamBrief
from app.schemas.user import UserBrief


class ClipCreate(BaseModel):
    """Body for POST /clips. duration_ms/source_fps are read off the
    browser's <video> element, so a draft has something to show. The worker
    overwrites both with ffprobe's values (6a)."""

    content_type: str
    duration_ms: int = Field(gt=0, le=30_000)  # clips are capped at 30s
    source_fps: int = Field(gt=0, le=240)
    # False skips the analyzer (F4): the worker only transcodes, the clip
    # becomes `analyzed` with no score, and its tricks can be tagged right
    # away. See app/models/clip.py.
    analyze: bool = True


class TrickOut(BaseModel):
    id: uuid.UUID
    canonical_name: str
    # Which entry of `analysis.tricks` this tag names, or null (a clip
    # posted without analysis, or tagged before F4: then tag i names entry i).
    analysis_index: int | None = None


class AnalyzedTrickOut(BaseModel):
    """One trick the analyzer found in the clip (6c-3), in clip order. Not
    the user's trick tags (`ClipOut.tricks`): the analyzer never names a
    trick. A tag says which of these it names with `analysis_index`."""

    # `landed`, `bailed`, or why it couldn't be judged ("trick left the
    # frame", "analysis failed for this trick", ...). Only landed tricks
    # are scored.
    outcome: str
    takeoff_ms: int | None = None  # into the clip, for jumping to the trick
    touchdown_ms: int | None = None
    confidence: float
    # Same keys as steeze_breakdown, null where n/a. Null when not landed.
    subscores: dict[str, float | None] | None = None


class AnalysisOut(BaseModel):
    # protected_namespaces=(): "model_version" collides with pydantic's
    # reserved "model_" prefix otherwise, and it's the right field name here.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    model_version: str
    confidence: Decimal
    # All six subscores, each averaged over the landed tricks; null where
    # it's n/a for every one of them (catch on an ollie). Null entirely
    # when the clip is unanalyzable.
    steeze_breakdown: dict[str, float | None] | None = None
    failure_reason: str | None = None
    # Empty for analyses without details (stub-v1 before 6c-3, media
    # failures, "analysis failed"). Also filled for unanalyzable clips, so
    # the UI can say which trick failed and why.
    tricks: list[AnalyzedTrickOut] = []
    created_at: datetime


class ClipOut(BaseModel):
    id: uuid.UUID
    status: ClipStatus
    author: UserBrief
    # The processed/ transcode's CDN URL once the worker has made one (6a);
    # until then (or for clips from before 6a), a presigned URL for the raw
    # upload. Built at response time either way, never stored.
    video_url: str
    thumb_url: str | None = None  # CDN URL of the poster frame, same lifecycle
    duration_ms: int | None = None
    source_fps: int | None = None
    steeze_score: Decimal | None = None
    published_at: datetime | None = None
    tricks: list[TrickOut] = []
    analysis: AnalysisOut | None = None
    like_count: int = 0
    comment_count: int = 0
    view_count: int = 0  # a raw play-count, not deduped to unique viewers (4d)
    liked_by_me: bool = False  # always false for anon viewers, same as UserPublic.followed_by_me
    # Set via PATCH /clips/{id}/team, only while status == ANALYZED — a
    # one-time, pre-publish decision (4c). Null if untagged.
    team: TeamBrief | None = None
    # Whether steeze_score counts toward an average (4d). True by default;
    # unlike `team`, this stays editable via PATCH /clips/{id}/score-inclusion
    # even after publishing (see app/models/clip.py).
    score_included: bool = True
    # False when the skater skipped analysis at upload (F4).
    analyze: bool = True
    created_at: datetime


class ClipCreateOut(BaseModel):
    """POST /clips returns the row plus the one-time presigned upload URL,
    together, so the client doesn't need a second round trip."""

    clip: ClipOut
    upload_url: str


class FeedPage(BaseModel):
    """One page of the home feed. `next_cursor` is null at the end — pass it
    back as `?cursor=` to get the following page (keyset, not offset)."""

    items: list[ClipOut]
    next_cursor: str | None = None


class ClipTeamUpdate(BaseModel):
    """Body for PATCH /clips/{id}/team. `team_id: null` clears it."""

    team_id: uuid.UUID | None = None


class ClipScoreInclusionUpdate(BaseModel):
    """Body for PATCH /clips/{id}/score-inclusion."""

    included: bool


class TrickTagIn(BaseModel):
    """One tag: a trick name, and which analyzed trick it names."""

    name: str
    # Index into the clip's `analysis.tricks`. Null when the clip has no
    # analysis, or to tag by position alone (the pre-F4 behaviour).
    analysis_index: int | None = Field(default=None, ge=0)


class TagTricksRequest(BaseModel):
    """Body for POST /clips/{id}/tricks, replacing any earlier tags, in line
    order. Each item is a plain name or a `TrickTagIn`; an analyzed trick
    left out (one the skater says isn't a trick) simply isn't tagged.
    Names are get-or-create against `tricks`, no fuzzy/alias matching yet
    (see docs/components/data-model.md's design notes)."""

    tricks: list[str | TrickTagIn] = Field(min_length=1, max_length=5)

    @field_validator("tricks")
    @classmethod
    def _validate_tricks(cls, v: list[str | TrickTagIn]) -> list[TrickTagIn]:
        tags = [
            TrickTagIn(name=t.strip())
            if isinstance(t, str)
            else TrickTagIn(name=t.name.strip(), analysis_index=t.analysis_index)
            for t in v
        ]
        if any(not (1 <= len(t.name) <= 60) for t in tags):
            raise ValueError("each trick name must be 1-60 characters")
        indexes = [t.analysis_index for t in tags if t.analysis_index is not None]
        if len(indexes) != len(set(indexes)):
            raise ValueError("each analyzed trick can be tagged once")
        return tags
