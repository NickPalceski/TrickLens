"""skip-analysis flag, tags that name an analyzed trick, reports

Frontend phase F4, the routes the web app proposed (docs/components/
frontend.md, Endpoints the API doesn't have yet):

- `clips.analyze`: false when the skater turned analysis off. The worker
  still transcodes the clip but doesn't score it. Server default true, so
  the still-live old code's inserts keep working during the deploy (step-5
  migration rule, docs/components/infrastructure.md).
- `clip_tricks.analysis_index`: which entry of the latest analysis's
  `details.tricks` a tag names. Nullable, no backfill: older tags and
  clips posted without analysis have none.
- `reports` (+ enum `report_kind`): analysis and bug reports from the app.
  Never sent anywhere else; the repo is public.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# create_type=False plus an explicit create(): see the CLAUDE.md gotcha on
# Postgres enums in Alembic.
report_kind = postgresql.ENUM("analysis", "bug", name="report_kind", create_type=False)


def upgrade() -> None:
    op.add_column(
        "clips",
        sa.Column("analyze", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("clip_tricks", sa.Column("analysis_index", sa.SmallInteger(), nullable=True))

    report_kind.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", report_kind, nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "clip_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clips.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("body", postgresql.JSONB(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("share_video", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("reports")
    report_kind.drop(op.get_bind(), checkfirst=True)
    op.drop_column("clip_tricks", "analysis_index")
    op.drop_column("clips", "analyze")
