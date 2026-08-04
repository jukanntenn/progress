"""Pure cryptographic primitives shared by the CLI and the API.

These helpers (Argon2id password hashing + HS256 JWT issue/decode) have zero
project dependencies — only ``pwdlib`` and ``PyJWT``. Lifting them out of
``progress.api.auth`` (which also holds FastAPI-bound dependencies like
``OAuth2PasswordBearer`` and ``Depends(get_config)``) keeps the CLI from
reaching into the ``api`` package just to hash a password, breaking the
``cli -> api`` reverse dependency at the package layer.

The FastAPI-bound auth dependencies (``get_current_user`` / ``CurrentUser`` /
``OAuth2PasswordBearer``) stay in ``progress.api.auth``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

logger = logging.getLogger(__name__)

#: Hasher shared across the process (Argon2id, the modern default).
_password_hash = PasswordHash((Argon2Hasher(),))


def hash_password(plain: str) -> str:
    """Hash ``plain`` with Argon2id."""
    return _password_hash.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify ``plain`` against ``hashed``; constant-time via pwdlib."""
    return _password_hash.verify(plain, hashed)


def create_access_token(*, subject: str, secret_key: str, expires_minutes: int) -> str:
    """Issue a signed HS256 JWT for ``subject`` (the username)."""
    expire = datetime.now(tz=UTC) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "type": "access"}
    return jwt.encode(payload, secret_key, algorithm="HS256")


def create_refresh_token(*, subject: str, secret_key: str, expires_days: int) -> str:
    """Issue a long-lived refresh JWT for ``subject``."""
    expire = datetime.now(tz=UTC) + timedelta(days=expires_days)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expire,
        "type": "refresh",
        "jti": f"{subject}-{int(datetime.now(tz=UTC).timestamp() * 1000)}",
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(token: str, secret_key: str) -> str:
    """Decode an access JWT, returning the ``sub`` (username).

    Raises :class:`jwt.PyJWTError` on any validation failure (expired,
    bad signature, wrong type, missing subject). Callers translate this
    into an HTTP or CLI error as appropriate.
    """
    payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("Missing subject")
    return sub


def decode_refresh_token(token: str, secret_key: str) -> str:
    """Decode a refresh JWT, returning the ``sub`` (username).

    Raises :class:`jwt.PyJWTError` on any validation failure.
    """
    payload = jwt.decode(token, secret_key, algorithms=["HS256"])
    if payload.get("type") != "refresh":
        raise jwt.InvalidTokenError("Not a refresh token")
    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise jwt.InvalidTokenError("Missing subject")
    return sub


__all__ = [
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "hash_password",
    "verify_password",
]
