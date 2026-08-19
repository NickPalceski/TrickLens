"""cognito_sub required

Step 1 left users.cognito_sub nullable deliberately, until auth existed to
populate it. Step 2 wires up Cognito, so every row from here on is created
via the JIT-registration flow with a cognito_sub already in hand.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("users", "cognito_sub", existing_type=sa.String(64), nullable=False)


def downgrade() -> None:
    op.alter_column("users", "cognito_sub", existing_type=sa.String(64), nullable=True)
