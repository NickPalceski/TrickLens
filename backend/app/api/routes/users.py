"""User, profile, and follow endpoints.

Cognito owns signup/login entirely — the client talks to Cognito directly
(the app client is public, no secret involved) and only ever hands this API
a verified id token. The one thing Cognito can't do is create the app-side
row, so POST /users is a just-in-time registration step: the first
authenticated call after signing up, choosing the public `username` at that
point.
"""

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentClaims, CurrentUser, DbSession, OptionalUser
from app.api.serializers import user_public
from app.models.social import Follow
from app.models.user import Profile, User
from app.schemas.user import ProfileOut, ProfileUpdate, UserCreate, UserMe, UserPublic, UserUpdate

router = APIRouter(prefix="/users", tags=["users"])


async def _user_me(user: User, claims: dict, db: DbSession) -> UserMe:
    pub = await user_public(user, db, viewer=user)
    return UserMe(**pub.model_dump(), email=claims["email"])


async def _by_username(username: str, db: DbSession) -> User:
    user = await db.scalar(select(User).where(func.lower(User.username) == username.lower()))
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    return user


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
    return await _user_me(user, claims, db)


@router.get("/me")
async def read_me(user: CurrentUser, claims: CurrentClaims, db: DbSession) -> UserMe:
    return await _user_me(user, claims, db)


@router.patch("/me")
async def update_me(
    body: UserUpdate, user: CurrentUser, claims: CurrentClaims, db: DbSession
) -> UserMe:
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.flush()
    return await _user_me(user, claims, db)


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
async def read_public(username: str, db: DbSession, viewer: OptionalUser) -> UserPublic:
    user = await _by_username(username, db)
    return await user_public(user, db, viewer=viewer)


@router.post("/{username}/follow", status_code=status.HTTP_201_CREATED)
async def follow_user(username: str, me: CurrentUser, db: DbSession) -> UserPublic:
    target = await _by_username(username, db)
    if target.id == me.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "you can't follow yourself")

    already = await db.scalar(
        select(Follow.id).where(Follow.follower_id == me.id, Follow.followee_user_id == target.id)
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "already following")

    db.add(Follow(follower_id=me.id, followee_user_id=target.id))
    try:
        await db.flush()
    except IntegrityError as exc:  # lost a race against a concurrent follow
        raise HTTPException(status.HTTP_409_CONFLICT, "already following") from exc
    return await user_public(target, db, viewer=me)


@router.delete("/{username}/follow")
async def unfollow_user(username: str, me: CurrentUser, db: DbSession) -> UserPublic:
    target = await _by_username(username, db)
    # Idempotent: unfollowing someone you don't follow is a no-op 200.
    await db.execute(
        delete(Follow).where(Follow.follower_id == me.id, Follow.followee_user_id == target.id)
    )
    await db.flush()
    return await user_public(target, db, viewer=me)
