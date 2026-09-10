"""Social graph. Follows now; likes and comments arrive in 4b."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKey


class Follow(Base, UUIDPrimaryKey):
    """One follow edge. The target is polymorphic — a user or a team — but
    modelled as two nullable FKs plus a check constraint, not an untyped
    (type, id) pair (see docs/ARCHITECTURE.md §6). Postgres then enforces
    referential integrity and cascade-deletes on both, which a bare
    `followee_id` never could.

    `followee_team_id`'s FK to `teams` is added in migration 0005 (4c) —
    that table doesn't exist yet. The column and the XOR check are here now
    so 0004 doesn't need revisiting.
    """

    __tablename__ = "follows"
    __table_args__ = (
        CheckConstraint(
            "(followee_user_id IS NOT NULL) <> (followee_team_id IS NOT NULL)",
            name="ck_follows_exactly_one_followee",
        ),
        # Nullable columns: Postgres treats NULLs as distinct here, so these
        # only bite for the non-null case — exactly what's wanted (you can
        # follow a given user once, and separately follow a given team once).
        UniqueConstraint("follower_id", "followee_user_id", name="uq_follows_user"),
        UniqueConstraint("follower_id", "followee_team_id", name="uq_follows_team"),
    )

    # No standalone index on follower_id: both unique constraints above lead
    # with it, so "who does X follow" queries are already covered (see
    # CLAUDE.md — redundant indexes). followee_* need their own, being the
    # trailing column of a composite unique.
    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    followee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    followee_team_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
