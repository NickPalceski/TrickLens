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
