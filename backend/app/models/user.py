"""User and profile models."""

import uuid
from decimal import Decimal

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey
from app.models.enums import SkateStyle, Stance


class User(Base, UUIDPrimaryKey, TimestampMixin):
    """Identity + the fields read on every feed render.

    Kept deliberately narrow: this table is joined on essentially every query
    in the app, so rarely-read personalization lives in Profile instead.
    """

    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness: "Nick" and "nick" cannot both exist.
        # A functional unique index does this without needing the citext
        # extension, and doubles as the lookup index for profile URLs.
        Index("ix_users_username_lower", text("lower(username)"), unique=True),
    )

    # Links to the Cognito user pool. Nullable until step 2 wires up auth.
    # unique=True already creates the backing index — index=True as well would
    # build a second, redundant one.
    cognito_sub: Mapped[str | None] = mapped_column(String(64), unique=True)

    username: Mapped[str] = mapped_column(String(30), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(60))
    bio: Mapped[str | None] = mapped_column(Text)

    # S3 key, never a URL. Storing URLs means every row breaks the day a CDN
    # goes in front of the bucket.
    avatar_key: Mapped[str | None] = mapped_column(String(512))

    profile: Mapped["Profile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class Profile(Base, TimestampMixin):
    """Setup preferences. 1:1 with User.

    Split out because every field is optional, rarely read, and would
    otherwise bloat the hot users table.
    """

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )

    stance: Mapped[Stance | None] = mapped_column(SAEnum(Stance, name="stance", native_enum=True))
    style: Mapped[SkateStyle | None] = mapped_column(
        SAEnum(SkateStyle, name="skate_style", native_enum=True)
    )

    board: Mapped[str | None] = mapped_column(String(80))
    board_size: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))  # inches, e.g. 8.25
    wheels: Mapped[str | None] = mapped_column(String(80))
    wheel_size: Mapped[int | None] = mapped_column()  # mm
    trucks: Mapped[str | None] = mapped_column(String(80))
    bearings: Mapped[str | None] = mapped_column(String(80))

    user: Mapped["User"] = relationship(back_populates="profile")
