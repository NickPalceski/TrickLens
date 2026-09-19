"""Teams: rosters, founding invites, and join requests.

A team doesn't exist for anyone but its owner and its founding invitees
until it's fully formed — see `Team.founded_at` and the state machine in
routes/teams.py. `TeamJoinRequest` deliberately serves both directions
(self-service requests and owner/admin invites, including the founding
ones) via `kind` rather than two near-identical tables — see enums.py's
`JoinRequestKind` docstring.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import JoinPolicy, JoinRequestKind, TeamLevel, TeamRole, sa_enum
from app.models.user import User

# Hard cap on `team_members` rows for one team, enforced wherever a
# membership is created (join, invite-accept, request-accept) — never in the
# schema, since "count of a related table" isn't something a CHECK
# constraint can express.
TEAM_MAX_MEMBERS = 20

# A team isn't founded until the owner plus at least this many invited
# co-founders have all accepted (docs/ARCHITECTURE.md §6). The creator can
# invite more than this up front if they want; this is only the floor.
TEAM_MIN_FOUNDING_INVITES = 2


class Team(Base, UUIDPrimaryKey, TimestampMixin):
    """A group of skaters whose published clips can be tagged to it and
    whose combined score Discover will rank (4d).

    `founded_at` is null from creation until every founding invite has been
    accepted — same idiom as `Clip.published_at`: a null timestamp marks an
    not-yet-real row rather than a separate status enum. While null, the
    team is invisible to everyone except the owner and its invitees, and
    can't be joined, followed, or tagged onto a clip (routes/teams.py).
    """

    __tablename__ = "teams"

    name: Mapped[str] = mapped_column(String(60), nullable=False)
    # Case-insensitive unique, chosen by the owner at creation and immutable
    # after — same treatment as `users.username` (see the functional index
    # on that table); no display-casing concern here either.
    slug: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    level: Mapped[TeamLevel] = mapped_column(sa_enum(TeamLevel, "team_level"), nullable=False)
    join_policy: Mapped[JoinPolicy] = mapped_column(
        sa_enum(JoinPolicy, "join_policy"), nullable=False, default=JoinPolicy.OPEN
    )
    # No ondelete cascade/set-null: a user who owns a team can't be deleted
    # out from under it. There's no account-deletion endpoint yet, so this
    # is precautionary rather than something the app can currently trigger.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    founded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner: Mapped[User] = relationship(lazy="selectin", viewonly=True)


class TeamMember(Base):
    """One membership row. No surrogate id — same reasoning as `Like`: a
    membership has no identity beyond "this user is on this team"."""

    __tablename__ = "team_members"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    role: Mapped[TeamRole] = mapped_column(sa_enum(TeamRole, "team_role"), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # No relationship back to Team: nothing in this codebase navigates
    # team -> members via the ORM (team_out() and the roster endpoint both
    # query TeamMember directly, same as Like/Follow never get a
    # User.likes-style relationship either) — only user is needed, to embed
    # a UserBrief.
    user: Mapped[User] = relationship(lazy="selectin", viewonly=True)


class TeamJoinRequest(Base):
    """One pending, not-yet-resolved membership — either direction (see
    `JoinRequestKind`). No surrogate id and no `status` column: existence
    means pending, and resolution always either deletes this row (reject) or
    deletes it while inserting a `TeamMember` (accept) — same hard-delete
    idiom as `Follow`/`Like`, no history kept."""

    __tablename__ = "team_join_requests"

    team_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    kind: Mapped[JoinRequestKind] = mapped_column(
        sa_enum(JoinRequestKind, "join_request_kind"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(lazy="selectin", viewonly=True)
    # Needed by GET /teams/invites/mine, which lists a user's pending
    # invites across many different teams and so can't rely on a slug
    # already in the URL the way the team-scoped listings can.
    team: Mapped["Team"] = relationship(lazy="selectin", viewonly=True)
