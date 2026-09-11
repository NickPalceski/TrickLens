"""follows

Step 4a. Polymorphic follow target as two nullable FKs + a check constraint
(see docs/ARCHITECTURE.md §6). followee_team_id's FK to `teams` is deferred
to 0006 (4c) — that table doesn't exist yet.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "follows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "follower_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "followee_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        # FK to teams.id added in 0006 — teams doesn't exist yet.
        sa.Column("followee_team_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "(followee_user_id IS NOT NULL) <> (followee_team_id IS NOT NULL)",
            name="ck_follows_exactly_one_followee",
        ),
        sa.UniqueConstraint("follower_id", "followee_user_id", name="uq_follows_user"),
        sa.UniqueConstraint("follower_id", "followee_team_id", name="uq_follows_team"),
    )
    # No index on follower_id alone: both unique constraints lead with it.
    op.create_index("ix_follows_followee_user_id", "follows", ["followee_user_id"])
    op.create_index("ix_follows_followee_team_id", "follows", ["followee_team_id"])


def downgrade() -> None:
    op.drop_table("follows")
