"""Discover (4d): a materialized weekly top-clips snapshot, and each team's
score history. Both are written only by app/rankings.py's rebuild job, never
by request-handling code — see docs/ARCHITECTURE.md §7 for why Discover is
precomputed rather than ranked live.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class ClipRanking(Base):
    """One row per clip eligible for this week's Discover clip rankings,
    fully replaced on every rebuild (routes/discover.py reads it, never
    writes it). `clip_id` is the primary key directly — like `Like`, this
    table's whole reason to exist is "one snapshot row per clip", not an
    identity of its own.

    Carries its own copies of `steeze_score`/`score_included` and the three
    raw engagement counts, rather than joining back to `clips` for them, so
    a rebuild is a single pass with no need to reconcile against
    since-changed rows — the snapshot is deliberately frozen until the next
    rebuild. Display data (routes/discover.py) re-fetches the live `Clip`
    for whatever this table says is in rank order, so counts shown to a
    viewer are always current even though the *ordering* is only as fresh
    as the last rebuild.
    """

    __tablename__ = "clip_rankings"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True
    )
    # Null exactly when the clip's analysis has no score to give — can't
    # happen for a published clip today (publish requires analyzed), but
    # nullable here costs nothing and avoids relying on that invariant
    # holding forever.
    steeze_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    # Copied at capture time so `sort=score` can filter on it without a
    # join back to `clips` — see the class docstring.
    score_included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    like_count: Mapped[int] = mapped_column(Integer, nullable=False)
    comment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    view_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # view_count*1 + like_count*5 + comment_count*10 (app/rankings.py's
    # ENGAGEMENT_WEIGHTS) — comments weighted highest, views lowest: a view
    # is nearly free, a like takes a tap, a comment takes real effort.
    engagement_score: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TeamScoreHistory(Base, UUIDPrimaryKey):
    """One team score snapshot, taken every rebuild. Append-only, same
    reasoning as `Analysis` — needed because Discover ranks teams by score
    *increase*, and a delta is uncomputable without history."""

    __tablename__ = "team_score_history"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Null exactly when the team had no eligible clips at capture time.
    score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
