"""analysis details

Step 6c-3. The real analyzer stores the evidence behind each analysis:
per trick, its times, outcome, the landed check's counts, the raw
measurements and the subscores (app/analyzer/pipeline.py,
AnalysisResult.details). 6d recalculates scores from these measurements
without re-running video, which also works for clips whose raw upload has
expired. Nullable with no backfill: stub analyses and every analysis
before 6c-3 have none, and the still-live old code (step-5 migration rule,
docs/components/infrastructure.md) never writes it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("details", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "details")
