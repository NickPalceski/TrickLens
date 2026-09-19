"""Team API schemas.

Split by direction on purpose, same as schemas/user.py and schemas/clip.py.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import JoinPolicy, TeamLevel, TeamRole
from app.models.team import TEAM_MIN_FOUNDING_INVITES
from app.schemas.user import UserBrief

# Same shape as users.username's validation (schemas/user.py) — slugs get
# the identical case-insensitive-unique, no-display-casing treatment.
_SLUG_RE = re.compile(r"^[a-z0-9_]{3,30}$")


class TeamCreate(BaseModel):
    """Body for POST /teams. Founding a team isn't instant — see
    app/models/team.py — so this also carries the required founding
    invitees; the team stays invisible to everyone else until they all
    accept."""

    name: str = Field(min_length=1, max_length=60)
    slug: str = Field(min_length=3, max_length=30)
    description: str | None = Field(default=None, max_length=2000)
    level: TeamLevel
    join_policy: JoinPolicy = JoinPolicy.OPEN
    invitee_usernames: list[str] = Field(min_length=TEAM_MIN_FOUNDING_INVITES)

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if not _SLUG_RE.fullmatch(v):
            raise ValueError("slug must be 3-30 lowercase letters, digits, or underscores")
        return v

    @field_validator("invitee_usernames")
    @classmethod
    def _validate_invitees(cls, v: list[str]) -> list[str]:
        lowered = [u.lower() for u in v]
        if len(set(lowered)) != len(lowered):
            raise ValueError("invitee usernames must be unique")
        return lowered


class TeamUpdate(BaseModel):
    """All fields optional — this is a PATCH, not a replace. `slug` is
    immutable, same as `username`."""

    name: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=2000)
    level: TeamLevel | None = None
    join_policy: JoinPolicy | None = None


class TeamBrief(BaseModel):
    """Minimal team card, for embedding elsewhere — a tagged clip's team,
    same idea as UserBrief."""

    id: uuid.UUID
    name: str
    slug: str


class TeamMemberOut(BaseModel):
    user: UserBrief
    role: TeamRole
    joined_at: datetime


class TeamJoinRequestOut(BaseModel):
    """One pending self-service join request, as shown to a team's
    owner/admin on GET /teams/{slug}/join-requests (kind=request only —
    invites aren't the team's to act on, see JoinRequestKind)."""

    user: UserBrief
    created_at: datetime


class TeamInviteOut(BaseModel):
    """One pending invite — founding or not — as shown to the invited user
    on GET /teams/invites/mine."""

    team: TeamBrief
    created_at: datetime


class TeamInviteCreate(BaseModel):
    """Body for POST /teams/{slug}/invites — a post-founding invite sent by
    an owner/admin."""

    username: str


class TeamOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None = None
    level: TeamLevel
    join_policy: JoinPolicy
    owner: UserBrief
    member_count: int = 0
    follower_count: int = 0
    followed_by_me: bool = False
    my_role: TeamRole | None = None  # null for non-members and anon viewers
    founded: bool = True
    # Only non-empty while founded=False — the outstanding founding
    # invitees. Visible only to the owner and the invitees themselves, since
    # they're the only ones who can see the team at all before it's founded
    # (routes/teams.py enforces that visibility rule).
    pending_founders: list[UserBrief] = []
    created_at: datetime


class TeamRoleUpdate(BaseModel):
    """Body for PATCH /teams/{slug}/members/{username} — owner-only.
    Ownership itself can't be transferred this way; the owner must delete
    the team instead."""

    role: TeamRole

    @field_validator("role")
    @classmethod
    def _not_owner(cls, v: TeamRole) -> TeamRole:
        if v is TeamRole.OWNER:
            raise ValueError("ownership can't be transferred — delete the team instead")
        return v
