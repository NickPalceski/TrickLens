"""Model package.

Every model must be imported here. Alembic's autogenerate only sees tables
registered on Base.metadata, and a model that is never imported is invisible
to it — which silently produces migrations that drop tables.
"""

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import ClipStatus, SkateStyle, Stance
from app.models.user import Profile, User

__all__ = [
    "Base",
    "ClipStatus",
    "Profile",
    "SkateStyle",
    "Stance",
    "TimestampMixin",
    "UUIDPrimaryKey",
    "User",
]
