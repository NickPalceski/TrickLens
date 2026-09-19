"""teams

Step 4c. `teams` isn't visible/joinable/followable until `founded_at` is set
— see app/models/team.py — which needs every founding invite (a
`team_join_requests` row with kind=invite) accepted first. `team_members`
and `team_join_requests` both use composite primary keys, no surrogate id,
same reasoning as `likes`. Also adds the two columns `clips`/`follows` were
left with placeholders for: `clips.team_id` (+ `score_included`, a new 4c
decision — see docs/ARCHITECTURE.md §6) and the deferred FK on
`follows.followee_team_id` (added back in 0004).

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # create_type=False + explicit .create(): see CLAUDE.md gotchas.
    team_level = postgresql.ENUM(
        "beginner", "intermediate", "advanced", name="team_level", create_type=False
    )
    team_level.create(op.get_bind(), checkfirst=True)
    join_policy = postgresql.ENUM(
        "open", "request", "invite_only", name="join_policy", create_type=False
    )
    join_policy.create(op.get_bind(), checkfirst=True)
    team_role = postgresql.ENUM("owner", "admin", "member", name="team_role", create_type=False)
    team_role.create(op.get_bind(), checkfirst=True)
    join_request_kind = postgresql.ENUM(
        "request", "invite", name="join_request_kind", create_type=False
    )
    join_request_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "teams",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("slug", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("level", team_level, nullable=False),
        sa.Column("join_policy", join_policy, nullable=False, server_default="open"),
        # No ondelete: a user who owns a team can't be deleted out from
        # under it. No account-deletion endpoint exists yet either way.
        sa.Column(
            "owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        # Null until every founding invite is accepted — see app/models/team.py.
        sa.Column("founded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.UniqueConstraint("slug", name="uq_teams_slug"),
    )
    # Case-insensitive uniqueness, same treatment as users.username.
    op.create_index("ix_teams_slug_lower", "teams", [sa.text("lower(slug)")], unique=True)
    op.create_index("ix_teams_owner_id", "teams", ["owner_id"])

    op.create_table(
        "team_members",
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", team_role, nullable=False),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    # Indexed on its own: the PK leads with team_id, so "which teams is this
    # user on" needs a dedicated index — same reasoning as likes.clip_id.
    op.create_index("ix_team_members_user_id", "team_members", ["user_id"])

    op.create_table(
        "team_join_requests",
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("kind", join_request_kind, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )
    op.create_index("ix_team_join_requests_user_id", "team_join_requests", ["user_id"])

    op.add_column(
        "clips",
        sa.Column(
            "team_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_clips_team_id", "clips", ["team_id"])
    op.add_column(
        "clips",
        sa.Column("score_included", sa.Boolean(), nullable=False, server_default=sa.true()),
    )

    # The deferred FK from 0004 — `teams` exists now.
    op.create_foreign_key(
        "fk_follows_followee_team_id_teams",
        "follows",
        "teams",
        ["followee_team_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_follows_followee_team_id_teams", "follows", type_="foreignkey")
    op.drop_column("clips", "score_included")
    op.drop_index("ix_clips_team_id", table_name="clips")
    op.drop_column("clips", "team_id")
    op.drop_index("ix_team_join_requests_user_id", table_name="team_join_requests")
    op.drop_table("team_join_requests")
    op.drop_index("ix_team_members_user_id", table_name="team_members")
    op.drop_table("team_members")
    op.drop_index("ix_teams_owner_id", table_name="teams")
    op.drop_index("ix_teams_slug_lower", table_name="teams")
    op.drop_table("teams")
    postgresql.ENUM(name="join_request_kind").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="team_role").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="join_policy").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="team_level").drop(op.get_bind(), checkfirst=True)
