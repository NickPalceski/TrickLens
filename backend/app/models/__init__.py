"""Model package.

Every model must be imported here. Alembic's autogenerate only sees tables
registered on Base.metadata, and a model that is never imported is invisible
to it — which silently produces migrations that drop tables.
"""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.clip import Analysis, Clip, ClipTrick, Trick
from app.models.discover import ClipRanking, TeamScoreHistory
from app.models.enums import (
    ClipStatus,
    JoinPolicy,
    JoinRequestKind,
    SkateStyle,
    Stance,
    TeamLevel,
    TeamRole,
)
from app.models.social import ClipView, Comment, Follow, Like
from app.models.team import Team, TeamJoinRequest, TeamMember
from app.models.user import Profile, User

__all__ = [
    "Analysis",
    "Base",
    "Clip",
    "ClipRanking",
    "ClipStatus",
    "ClipTrick",
    "ClipView",
    "Comment",
    "Follow",
    "JoinPolicy",
    "JoinRequestKind",
    "Like",
    "Profile",
    "SkateStyle",
    "Stance",
    "Team",
    "TeamJoinRequest",
    "TeamLevel",
    "TeamMember",
    "TeamRole",
    "TeamScoreHistory",
    "TimestampMixin",
    "Trick",
    "UUIDPrimaryKey",
    "User",
]
