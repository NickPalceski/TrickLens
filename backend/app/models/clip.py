"""Clip, analysis, and trick models.

A clip moves through ClipStatus (see enums.py) from draft to published.
Trick identity is never predicted — see docs/ARCHITECTURE.md §4 — so
clip_tricks is always user-supplied, never analyzer output.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import ClipStatus, sa_enum
from app.models.team import Team
from app.models.user import User


class Clip(Base, UUIDPrimaryKey, TimestampMixin):
    """A single uploaded clip and its place in the upload -> publish pipeline.

    Stays a draft — invisible to anyone but its owner — until explicitly
    published. A failed or unflattering analysis must never reach a feed.
    """

    __tablename__ = "clips"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[ClipStatus] = mapped_column(
        sa_enum(ClipStatus, "clip_status"), nullable=False, default=ClipStatus.DRAFT
    )
    # Set only via PATCH /clips/{id}/team, only while status == ANALYZED —
    # a one-time, pre-publish decision (4c). ON DELETE SET NULL, unlike
    # user_id's CASCADE: a team disbanding shouldn't take anyone's clips
    # with it, just detach the credit.
    team_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    # Whether this clip's steeze_score counts toward its owner's (or tagged
    # team's) average once Discover (4d) computes one. True by default;
    # unlike team_id this stays editable forever via
    # PATCH /clips/{id}/score-inclusion, even after publishing — skate clips
    # are often shot from angles the analyzer scores unreliably, and users
    # shouldn't have to choose between a visually great clip and their
    # average.
    score_included: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # S3 key, never a URL — see CLAUDE.md conventions. Assigned at creation,
    # before the browser has uploaded anything, so it can be presigned.
    s3_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # Stays null until step 6 adds ffmpeg thumbnailing to the worker.
    thumb_key: Mapped[str | None] = mapped_column(String(512))

    # Client-reported (read off the browser's <video> element), not yet
    # server-verified — the stub worker has no ffprobe. Step 6 can cross-check
    # these once the worker actually decodes the video.
    duration_ms: Mapped[int | None] = mapped_column()
    source_fps: Mapped[int | None] = mapped_column()

    steeze_score: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Read-only, eager: the feed and every clip response embed the author.
    # The cascade on delete is handled by user_id's FK, not here.
    user: Mapped[User] = relationship(lazy="selectin", viewonly=True)
    # Eager, same reasoning as `user` — ClipOut embeds a TeamBrief whenever a
    # clip is tagged, None when team_id is null. NOT viewonly, unlike
    # `user`: routes/clips.py's set_clip_team writes through this
    # relationship (`clip.team = team`) rather than setting team_id
    # directly, specifically so the in-memory attribute stays in sync with
    # no extra re-fetch (see that route's comment) — a viewonly relationship
    # would silently drop that write instead of persisting it, which is
    # exactly the bug this comment is here to prevent reintroducing.
    team: Mapped[Team | None] = relationship(lazy="selectin")

    # Newest first, so `clip.analyses[0]` is always the latest pass — a clip
    # could in principle be re-analyzed later (a model upgrade), so this
    # isn't a strict 1:1 the way `analyses.clip_id` might suggest.
    analyses: Mapped[list["Analysis"]] = relationship(
        back_populates="clip",
        cascade="all, delete-orphan",
        order_by="Analysis.created_at.desc()",
        lazy="selectin",
    )
    clip_tricks: Mapped[list["ClipTrick"]] = relationship(
        back_populates="clip",
        cascade="all, delete-orphan",
        order_by="ClipTrick.position",
        lazy="selectin",
    )


class Analysis(Base, UUIDPrimaryKey):
    """One scoring pass over a clip. Append-only, not updated in place."""

    __tablename__ = "analyses"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)

    # Null exactly when the confidence gate rejected the clip — see the
    # "fail safe" decision in docs/ARCHITECTURE.md §4: a specific reason,
    # never a guess.
    steeze_breakdown: Mapped[dict | None] = mapped_column(JSONB)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    clip: Mapped["Clip"] = relationship(back_populates="analyses")


class Trick(Base, UUIDPrimaryKey):
    """A canonical trick name. Always user-supplied — trick identity is
    never predicted, only scored (docs/ARCHITECTURE.md §4)."""

    __tablename__ = "tricks"

    # Stored pre-normalized (lowercased, trimmed) by the API layer, so a
    # plain unique constraint is enough — unlike users.username, there's no
    # display casing to preserve here.
    canonical_name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)


class ClipTrick(Base):
    """One tagged trick on a clip, in line order."""

    __tablename__ = "clip_tricks"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    trick_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tricks.id"), nullable=False, index=True
    )

    clip: Mapped["Clip"] = relationship(back_populates="clip_tricks")
    trick: Mapped["Trick"] = relationship(lazy="selectin")
