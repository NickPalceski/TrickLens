"""Unit tests for Cognito id-token verification.

Signs tokens with a throwaway RSA keypair standing in for Cognito's JWKS, and
monkeypatches auth._jwks_client so verification never touches the network or
a real pool. That's deliberate: these should pass even before the dev pool
exists, and shouldn't flake on network access when it does.
"""

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.services import auth

_ISSUER = "https://cognito-idp.us-east-1.amazonaws.com/us-east-1_test"
_CLIENT_ID = "test-client-id"


@pytest.fixture
def private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(private_key, **overrides):
    now = int(time.time())
    claims = {
        "sub": "abc-123",
        "email": "skater@example.com",
        "token_use": "id",
        "aud": _CLIENT_ID,
        "iss": _ISSUER,
        "iat": now,
        "exp": now + 3600,
        **overrides,
    }
    return jwt.encode(claims, private_key, algorithm="RS256")


@pytest.fixture(autouse=True)
def _patched_settings_and_jwks(monkeypatch, private_key):
    settings = SimpleNamespace(cognito_client_id=_CLIENT_ID, cognito_issuer=_ISSUER)
    monkeypatch.setattr(auth, "get_settings", lambda: settings)

    class _FakeSigningKey:
        key = private_key.public_key()

    class _FakeJWKClient:
        def get_signing_key_from_jwt(self, token):
            return _FakeSigningKey()

    monkeypatch.setattr(auth, "_jwks_client", lambda: _FakeJWKClient())


def test_valid_id_token_returns_claims(private_key):
    claims = auth.verify_id_token(_token(private_key))
    assert claims["sub"] == "abc-123"
    assert claims["email"] == "skater@example.com"


def test_rejects_access_token(private_key):
    with pytest.raises(HTTPException):
        auth.verify_id_token(_token(private_key, token_use="access"))


def test_rejects_wrong_audience(private_key):
    with pytest.raises(HTTPException):
        auth.verify_id_token(_token(private_key, aud="someone-else"))


def test_rejects_expired_token(private_key):
    with pytest.raises(HTTPException):
        auth.verify_id_token(_token(private_key, exp=int(time.time()) - 10))


def test_rejects_wrong_issuer(private_key):
    with pytest.raises(HTTPException):
        auth.verify_id_token(_token(private_key, iss="https://not-cognito.example.com"))


def test_rejects_bad_signature(private_key):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException):
        auth.verify_id_token(_token(other_key))
