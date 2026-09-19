"""Shared enums, mapped to native Postgres enum types.

Defined centrally so the API, the worker, and the database agree on the exact
same vocabulary.
"""

from enum import StrEnum

from sqlalchemy import Enum as SAEnum


class Stance(StrEnum):
    REGULAR = "regular"
    GOOFY = "goofy"


class SkateStyle(StrEnum):
    VERT = "vert"
    STREET = "street"
    MIX = "mix"


class TeamLevel(StrEnum):
    """A team's self-declared skateboarding level, set by its owner at
    creation and editable afterward in team settings (docs/ARCHITECTURE.md
    §6). Purely descriptive — nothing enforces a member's own skill matches
    it."""

    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class JoinPolicy(StrEnum):
    """How a user other than an invitee ends up on a team's roster.

    OPEN: POST /teams/{slug}/join makes them a member immediately.
    REQUEST: that same call creates a pending `TeamJoinRequest` instead,
    which an owner/admin must accept.
    INVITE_ONLY: there is no self-serve join at all — only an owner/admin
    sending an invite (also a `TeamJoinRequest`, the other `kind`) can add
    someone.
    """

    OPEN = "open"
    REQUEST = "request"
    INVITE_ONLY = "invite_only"


class TeamRole(StrEnum):
    """A team member's permission level. Exactly one member per team holds
    OWNER (mirrors `Team.owner_id`); ADMIN can approve/reject join requests
    and kick a MEMBER, but not another ADMIN or the OWNER — only the owner
    changes roles or deletes the team. No ownership-transfer flow exists
    yet."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class JoinRequestKind(StrEnum):
    """Which direction a pending `TeamJoinRequest` row runs, since one table
    serves both (docs/ARCHITECTURE.md §6):

    REQUEST: the user asked to join; an owner/admin must accept it.
    INVITE: an owner/admin (or, during team founding, the creator) asked the
    user to join; only that user can accept or reject it.

    There is no `status` column — a row's existence means "pending"; accept
    replaces it with a `TeamMember` row, reject just deletes it (except
    rejecting a *founding* invite, which deletes the whole still-unfounded
    `Team` instead — see routes/teams.py).
    """

    REQUEST = "request"
    INVITE = "invite"


class ClipStatus(StrEnum):
    """Lifecycle of a clip.

    Defined now, used from step 3. The important property is that a clip is a
    *draft* until the user explicitly publishes it — so a failed analysis
    never reaches anyone's feed, and the user gets to tag and review first.
    """

    DRAFT = "draft"  # row created, waiting for the browser's upload to finish
    QUEUED = "queued"  # upload confirmed, message on SQS
    ANALYZING = "analyzing"  # worker picked it up
    ANALYZED = "analyzed"  # scored, awaiting user tagging + publish
    UNANALYZABLE = "unanalyzable"  # confidence gate rejected it (see failure_reason)
    PUBLISHED = "published"  # visible in feeds


def sa_enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    """Build the SQLAlchemy column type for one of the StrEnums above.

    SQLAlchemy's Enum type defaults to sending the Python member's *name*
    ("DRAFT") to the database, not its .value ("draft") — even for a
    StrEnum. Every native Postgres enum type here was created (via Alembic)
    with the lowercase values, so without values_callable every insert of a
    non-null enum column fails with "invalid input value for enum ...:
    DRAFT". Centralized here so the fix lives in one place instead of being
    repeated at every call site.
    """
    return SAEnum(
        enum_cls, name=name, native_enum=True, values_callable=lambda e: [m.value for m in e]
    )
