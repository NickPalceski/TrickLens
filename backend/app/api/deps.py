"""Shared FastAPI dependencies."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User
from app.services.auth import verify_id_token

DbSession = Annotated[AsyncSession, Depends(get_db)]

_bearer = HTTPBearer()
_optional_bearer = HTTPBearer(auto_error=False)


async def get_current_claims(
    creds: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> dict[str, Any]:
    """Verified claims from the caller's Cognito id token."""
    return verify_id_token(creds.credentials)


CurrentClaims = Annotated[dict[str, Any], Depends(get_current_claims)]


async def get_current_user(claims: CurrentClaims, db: DbSession) -> User:
    """The caller's row in `users`.

    404, not 401: the token is valid, there just isn't an app user for it
    yet. Distinguishes "log in again" from "call POST /users first".
    """
    user = await db.scalar(select(User).where(User.cognito_sub == claims["sub"]))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no account for this login yet — POST /users to register",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_optional_bearer)],
    db: DbSession,
) -> User | None:
    """Like get_current_user, but returns None when there's no bearer token
    at all — for routes that are public yet show extra fields to a signed-in
    viewer (e.g. `followed_by_me`). A present-but-invalid token still 401s:
    silently ignoring a broken token would hide bugs.
    """
    if creds is None:
        return None
    claims = verify_id_token(creds.credentials)
    return await db.scalar(select(User).where(User.cognito_sub == claims["sub"]))


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
