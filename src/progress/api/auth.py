"""FastAPI-bound authentication dependencies.

The pure cryptographic primitives (Argon2id password hashing, HS256 JWT
issue/decode) live in :mod:`progress.utils.security` so the CLI can hash a
password without reaching into the ``api`` package. This module keeps only
the FastAPI-bound pieces: the ``OAuth2PasswordBearer`` scheme, the
``get_current_user`` / ``get_current_superuser`` route dependencies, and thin
wrappers that translate :class:`jwt.PyJWTError` into ``HTTPException(401)``.

Token transport is Bearer JWT (stateless): the SPA sends ``Authorization:
Bearer <token>`` and the server decodes it per-request.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt

from progress.api.deps import get_config
from progress.config.root import CoreConfig
from progress.db.models import User
from progress.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token as _decode_access_token,
    decode_refresh_token as _decode_refresh_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

#: The FastAPI security scheme. ``tokenUrl`` is OpenAPI metadata only — it tells
#: the Swagger "Authorize" button where login lives. ``auto_error=False`` so we
#: can distinguish "no token" (401) from "bad token" (401 with a clearer message)
#: inside :func:`get_current_user`.
_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def decode_access_token(token: str, secret_key: str) -> str:
    """Decode an access JWT, translating :class:`jwt.PyJWTError` into ``HTTPException(401)``."""
    try:
        return _decode_access_token(token, secret_key)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


def decode_refresh_token(token: str, secret_key: str) -> str:
    """Decode a refresh JWT, translating :class:`jwt.PyJWTError` into ``HTTPException(401)``."""
    try:
        return _decode_refresh_token(token, secret_key)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e


async def get_current_user(
    token: Annotated[str | None, Depends(_oauth2_scheme)],
    cfg: Annotated[CoreConfig, Depends(get_config)],
) -> User:
    """Resolve the bearer token to an active :class:`User`.

    When ``auth.enabled`` is ``False`` (dev/disable), a synthetic request-local
    admin is returned so routes still type-check. Otherwise the token must be
    present and valid.
    """
    if not cfg.auth.enabled:
        return await _disabled_auth_user()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    username = decode_access_token(token, cfg.auth.secret_key.get_secret_value())
    user = await User.filter(username=username, is_active=True).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def get_current_superuser(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Require the current user to be a superuser (HTTPException 403 otherwise)."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not enough permissions",
        )
    return current_user


async def _disabled_auth_user() -> User:
    """A synthetic admin returned when ``auth.enabled`` is False (dev only)."""
    user = User(username="anonymous", is_active=True, is_superuser=True)
    user.id = 0
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentSuperuser = Annotated[User, Depends(get_current_superuser)]


__all__ = [
    "CurrentSuperuser",
    "CurrentUser",
    "create_access_token",
    "create_refresh_token",
    "decode_access_token",
    "decode_refresh_token",
    "get_current_superuser",
    "get_current_user",
    "hash_password",
    "verify_password",
]
