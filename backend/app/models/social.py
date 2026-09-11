"""Social graph: follows, likes, comments. Teams arrive in 4c."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKey
from app.models.user import User


class Follow(Base, UUIDPrimaryKey):
    """One follow edge. The target is polymorphic — a user or a team — but
    modelled as two nullable FKs plus a check constraint, not an untyped
    (type, id) pair (see docs/ARCHITECTURE.md §6). Postgres then enforces
    referential integrity and cascade-deletes on both, which a bare
    `followee_id` never could.

    `followee_team_id`'s FK to `teams` is added in migration 0006 (4c) —
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


class Like(Base):
    """One like on a clip. No surrogate id — a like has no identity beyond
    "this user liked this clip" — same reasoning as `ClipTrick` in
    models/clip.py, so `(user_id, clip_id)` is the primary key directly."""

    __tablename__ = "likes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed: the PK leads with user_id, so "how many likes does clip X
    # have" needs its own index — same reasoning as followee_user_id above.
    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), primary_key=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Comment(Base, UUIDPrimaryKey):
    """One comment on a clip, optionally a reply to a top-level comment.

    Threading is capped at one level deep: a reply's `parent_id` must point
    at a top-level comment, never at another reply. That rule is a cross-row
    condition ("the referenced row's own parent_id is null"), which a plain
    CHECK constraint can't express without a trigger — this codebase has no
    procedural DB logic anywhere else, so it's enforced in the route
    (routes/clips.py) instead.

    No TimestampMixin: there's no edit endpoint yet, so no updated_at is
    needed — same as Analysis (append-only, plain created_at).
    """

    __tablename__ = "comments"

    clip_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clips.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # ondelete="CASCADE" + the ORM cascade on `replies` below: deleting a
    # top-level comment deletes its replies too, at both the DB and ORM
    # level — same belt-and-suspenders pattern Clip.analyses uses.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    author: Mapped[User] = relationship(lazy="selectin", viewonly=True)
    parent: Mapped["Comment | None"] = relationship(
        remote_side="Comment.id", back_populates="replies"
    )
    # lazy="raise_on_sql", not "selectin": SQLAlchemy never auto-applies a
    # relationship's default eager strategy for *self-referential*
    # relationships (unlike Clip.analyses/clip_tricks, which do auto-load —
    # this is specific to self-reference, presumably to avoid unbounded
    # recursive loading on tree-shaped data). A plain query for Comment
    # leaves `replies` unloaded, and touching it would silently attempt a
    # blocking lazy load — which crashes async SQLAlchemy with an opaque
    # MissingGreenlet instead of a clear error. raise_on_sql fails loudly
    # and immediately if a query forgets the explicit
    # `.options(selectinload(Comment.replies))` it actually needs — see
    # routes/clips.py's add_comment/list_comments.
    replies: Mapped[list["Comment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="Comment.created_at.asc()",
        lazy="raise_on_sql",
    )
