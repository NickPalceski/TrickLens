"""User and profile endpoints.

Cognito owns signup/login entirely — the client talks to Cognito directly
(the app client is public, no secret involved) and only ever hands this API
a verified id token. The one thing Cognito can't do is create the app-side
row, so POST /users is a just-in-time registration step: the first
authenticated call after signing up, choosing the public `username` at that
point.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentClaims, CurrentUser, DbSession
from app.models.user import Profile, User
from app.schemas.user import ProfileOut, ProfileUpdate, UserCreate, UserMe, UserPublic, UserUpdate
from app.services.storage import get_storage

router = APIRouter(prefix="/users", tags=["users"])


def _to_public(user: User) -> UserPublic:
    storage = get_storage()
    return UserPublic(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        bio=user.bio,
        avatar_url=storage.public_url(user.avatar_key) if user.avatar_key else None,
        profile=ProfileOut.model_validate(user.profile) if user.profile else None,
        created_at=user.created_at,
    )


def _to_user_me(user: User, claims: dict) -> UserMe:
    return UserMe(**_to_public(user).model_dump(), email=claims["email"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def register(body: UserCreate, claims: CurrentClaims, db: DbSession) -> UserMe:
    """JIT registration: the first call any newly-signed-up Cognito user
    makes, to pick their public username and create the app-side row."""
    existing = await db.scalar(select(User).where(User.cognito_sub == claims["sub"]))
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this login is already registered")

    user = User(cognito_sub=claims["sub"], username=body.username, display_name=body.display_name)
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "username already taken") from exc

    # Re-fetch through a normal query so the profile relationship's
    # lazy="selectin" loader populates it — a freshly constructed instance
    # that was only add()ed and flush()ed has no loaded relationships, and
    # touching one lazily outside a query would break under async SQLAlchemy.
    user = await db.scalar(select(User).where(User.id == user.id))
    return _to_user_me(user, claims)


@router.get("/me")
async def read_me(user: CurrentUser, claims: CurrentClaims) -> UserMe:
    return _to_user_me(user, claims)


@router.patch("/me")
async def update_me(
    body: UserUpdate, user: CurrentUser, claims: CurrentClaims, db: DbSession
) -> UserMe:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return _to_user_me(user, claims)


@router.patch("/me/profile")
async def update_profile(body: ProfileUpdate, user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = user.profile
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.flush()
    return ProfileOut.model_validate(profile)


@router.get("/{username}")
async def read_public(username: str, db: DbSession) -> UserPublic:
    user = await db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return _to_public(user)
