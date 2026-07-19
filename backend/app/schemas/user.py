"""User and profile API schemas.

Split by direction on purpose: ORM objects are never returned from a route,
so a column added to a model can never accidentally become public.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import SkateStyle, Stance


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
    """The authenticated user's own view. Diverges from UserPublic in step 2
    (email, notification settings, etc.)."""
