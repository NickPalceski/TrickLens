"""User and profile API schemas.

Split by direction on purpose: ORM objects are never returned from a route,
so a column added to a model can never accidentally become public.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import SkateStyle, Stance

# Lowercase-only at the schema level: the DB enforces case-insensitive
# uniqueness via lower(username), but two users differing only by case would
# otherwise both pass validation and then race on the same index entry.
_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,30}$")


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stance: Stance | None = None
    style: SkateStyle | None = None
    board: str | None = None
    board_size: Decimal | None = None
    wheels: str | None = None
    wheel_size: int | None = None
    trucks: str | None = None
    bearings: str | None = None


class ProfileUpdate(BaseModel):
    """All fields optional — this is a PATCH, not a replace."""

    stance: Stance | None = None
    style: SkateStyle | None = None
    board: str | None = Field(default=None, max_length=80)
    board_size: Decimal | None = Field(default=None, ge=6, le=12)
    wheels: str | None = Field(default=None, max_length=80)
    wheel_size: int | None = Field(default=None, ge=40, le=80)
    trucks: str | None = Field(default=None, max_length=80)
    bearings: str | None = Field(default=None, max_length=80)


class UserPublic(BaseModel):
    """Safe to show anyone."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    display_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None  # built from avatar_key at response time
    profile: ProfileOut | None = None
    created_at: datetime


class UserMe(UserPublic):
    """The authenticated user's own view.

    `email` comes from the verified id token, not the database — Cognito
    stays the source of truth for identity attributes so there is nothing to
    keep in sync.
    """

    email: str


class UserCreate(BaseModel):
    """Body for POST /users — JIT registration on first login."""

    username: str = Field(min_length=3, max_length=30)
    display_name: str | None = Field(default=None, max_length=60)

    @field_validator("username")
    @classmethod
    def _validate_username(cls, v: str) -> str:
        if not _USERNAME_RE.fullmatch(v):
            raise ValueError("username must be 3-30 lowercase letters, digits, or underscores")
        return v


class UserUpdate(BaseModel):
    """All fields optional — this is a PATCH, not a replace."""

    display_name: str | None = Field(default=None, max_length=60)
    bio: str | None = Field(default=None, max_length=2000)
