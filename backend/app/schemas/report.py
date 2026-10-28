"""Report schemas (F4): what the app's two report forms send. See
docs/components/frontend.md, Reports.

Every field is bounded: POST /bug-reports works signed out, so nothing
here may let one request store an unbounded amount.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analyzer.calibration import SUBSCORES

# What a skater can say is wrong with an analysis, the report form's checklist.
AnalysisProblem = Literal[
    "missed_trick",
    "extra_trick",
    "wrong_landed",
    "timing_off",
    "score_off",
    "should_have_scored",
    "wrong_reason",
]


class AnalysisReportCreate(BaseModel):
    """Body for POST /clips/{clip_id}/analysis-reports. Only what the
    skater says: the server snapshots the analysis itself."""

    model_config = ConfigDict(extra="forbid")

    problems: list[AnalysisProblem] = Field(default=[], max_length=7)
    # Which analyzed trick (index into analysis.tricks), or null for the
    # clip as a whole.
    trick_index: int | None = Field(default=None, ge=0)
    # With score_off: which subscores feel wrong, and which way.
    subscores: list[str] = Field(default=[], max_length=len(SUBSCORES))
    score_direction: Literal["too_high", "too_low"] | None = None
    note: str | None = Field(default=None, max_length=2000)
    # Consent to keep and watch the clip to improve the analyzer.
    share_video: bool = False
    app_version: str = Field(default="", max_length=40)

    @field_validator("subscores")
    @classmethod
    def _known_subscores(cls, v: list[str]) -> list[str]:
        unknown = set(v) - set(SUBSCORES)
        if unknown:
            raise ValueError(f"unknown subscores: {', '.join(sorted(unknown))}")
        return v


class BugContext(BaseModel):
    """Sent automatically with a bug report, and listed to the person on
    the form before they send it."""

    model_config = ConfigDict(extra="forbid")

    app_version: str = Field(max_length=40)
    user_agent: str = Field(max_length=500)
    viewport: str = Field(max_length=20)
    theme: str = Field(max_length=20)
    api_mode: str = Field(max_length=10)


class BugReportCreate(BaseModel):
    """Body for POST /bug-reports, signed in or out."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(max_length=4000)
    # The page it happened on, e.g. "/upload/…".
    page: str | None = Field(default=None, max_length=300)
    context: BugContext

    @field_validator("description")
    @classmethod
    def _says_something(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 10:
            raise ValueError("describe the problem in a few words")
        return v


class ReportCreated(BaseModel):
    id: uuid.UUID
    created_at: datetime
