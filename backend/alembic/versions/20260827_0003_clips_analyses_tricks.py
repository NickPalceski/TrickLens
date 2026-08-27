"""clips, analyses, tricks, clip_tricks

Step 3: upload -> S3 -> SQS -> worker. Deliberately omits the `team_id`
column ARCHITECTURE.md's planned `clips` schema shows — `teams` doesn't
exist until step 4, and a FK to a nonexistent table isn't an option. Step 4
adds the column then.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # create_type=False + explicit .create(): see CLAUDE.md gotchas. Without
    # it, referencing this same object in create_table() below emits a
    # second CREATE TYPE and the migration dies on "type already exists".
    clip_status = postgresql.ENUM(
        "draft",
        "queued",
        "analyzing",
        "analyzed",
        "unanalyzable",
        "published",
        name="clip_status",
        create_type=False,
    )
    clip_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "clips",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", clip_status, nullable=False, server_default="draft"),
        # S3 key, not a URL — see CLAUDE.md conventions.
        sa.Column("s3_key", sa.String(512), nullable=False),
        sa.Column("thumb_key", sa.String(512), nullable=True),
        # Client-reported until step 6 adds server-side ffprobe.
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("source_fps", sa.Integer(), nullable=True),
        sa.Column("steeze_score", sa.Numeric(4, 1), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_clips_user_id", "clips", ["user_id"])

    op.create_table(
        "analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Numeric(3, 2), nullable=False),
        # Null exactly when the confidence gate rejected the clip.
        sa.Column("steeze_breakdown", postgresql.JSONB(), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_analyses_clip_id", "analyses", ["clip_id"])

    op.create_table(
        "tricks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Pre-normalized (lowercased, trimmed) by the API — no functional
        # lower() index needed the way users.username needs one, since there
        # is no display casing to preserve here.
        sa.Column("canonical_name", sa.String(80), nullable=False),
        sa.Column(
            "aliases", postgresql.ARRAY(sa.String()), nullable=False, server_default="{}"
        ),
        sa.UniqueConstraint("canonical_name", name="uq_tricks_canonical_name"),
    )

    op.create_table(
        "clip_tricks",
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        # Part of the PK, not just a plain column: enforces one trick per
        # ordering slot per clip.
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column(
            "trick_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tricks.id"), nullable=False
        ),
    )
    op.create_index("ix_clip_tricks_trick_id", "clip_tricks", ["trick_id"])


def downgrade() -> None:
    op.drop_table("clip_tricks")
    op.drop_table("tricks")
    op.drop_index("ix_analyses_clip_id", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_clips_user_id", table_name="clips")
    op.drop_table("clips")
    postgresql.ENUM(name="clip_status").drop(op.get_bind(), checkfirst=True)
