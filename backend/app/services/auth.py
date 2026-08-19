"""Cognito token verification.

The one identity-aware module, same spirit as storage.py (S3) and queue.py
(SQS) being the only AWS-aware modules for their services. This one is a
partial exception to "LocalStack locally, real AWS in production": Cognito
is always the real service (see config.py) because there is no free, faithful
local emulator for it. Nothing here needs AWS credentials — JWKS endpoints
are public, so verification is a plain HTTPS fetch plus signature math.
"""

import asyncio
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, status

from app.config import get_settings


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    """Cached across requests: keys rotate rarely and PyJWKClient itself
    caches the fetched key set, so this just avoids re-creating the client.
    """
    return jwt.PyJWKClient(f"{get_settings().cognito_issuer}/.well-known/jwks.json")


def verify_id_token(token: str) -> dict[str, Any]:
    """Verify a Cognito id token and return its claims.

    The id token (not the access token) is what the API expects as the
    bearer credential — it carries `email`, which first-login registration
    needs, at the cost of one non-standard choice: most examples use the
    access token for API calls and the id token only client-side.

    Raises HTTPException(401) for anything wrong with the token.
    """
    settings = get_settings()
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.cognito_client_id,
            issuer=settings.cognito_issuer,
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if claims.get("token_use") != "id":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="expected an id token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return claims


async def check() -> None:
    """Health probe: confirm the pool's JWKS endpoint is reachable.

    No AWS credentials involved — this is the same public endpoint token
    verification hits on every request. Deliberately uncached (fetch_data
    hits the network directly) so this actually round-trips the dependency,
    matching how the postgres/s3/sqs checks work.
    """
    await asyncio.to_thread(_jwks_client().fetch_data)
