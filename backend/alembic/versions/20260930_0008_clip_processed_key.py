"""clip processed_key

Step 6a. The worker now writes a 720p transcode under processed/, and
clips play from it instead of the raw upload (which raw/'s 7-day lifecycle
rule deletes). Nullable with no backfill: clips analyzed before 6a have no
transcode, and the serializer falls back to presigning the raw key for
them. It also keeps the step-5 migration rule (see
docs/components/infrastructure.md): the still-live old code never writes
this column, so a null there is fine.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("clips", sa.Column("processed_key", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "processed_key")
