"""discover

Step 4d. `clip_views` is a plain append-only event log (no unique
constraint — a rewatch counts again). `clip_rankings` is fully truncated
and reinserted by every app/rankings.py run, so `clip_id` is its primary
key directly, same "no surrogate id" reasoning as `likes`. `team_score_history`
is append-only, same shape as `analyses`.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clip_views",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Nullable + SET NULL: no route records an anonymous view today,
        # but a deleted user's past views should still count toward a
        # clip's total rather than disappearing.
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "viewed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_clip_views_clip_id", "clip_views", ["clip_id"])

    op.create_table(
        "clip_rankings",
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("steeze_score", sa.Numeric(4, 1), nullable=True),
        sa.Column("score_included", sa.Boolean(), nullable=False),
        sa.Column("like_count", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("engagement_score", sa.Integer(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "team_score_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("score", sa.Numeric(4, 1), nullable=True),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_team_score_history_team_id", "team_score_history", ["team_id"])


def downgrade() -> None:
    op.drop_index("ix_team_score_history_team_id", table_name="team_score_history")
    op.drop_table("team_score_history")
    op.drop_table("clip_rankings")
    op.drop_index("ix_clip_views_clip_id", table_name="clip_views")
    op.drop_table("clip_views")
