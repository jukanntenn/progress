"""Auth endpoints: login, me, change-password (spec 12, auth addition).

``POST /api/v1/auth/login`` accepts a JSON body (``{username, password}``) and
returns ``{access_token, refresh_token, token_type}``. ``GET /api/v1/auth/me``
returns the current user. ``POST /api/v1/auth/change-password`` lets a user
update their own password. ``POST /api/v1/auth/refresh`` issues a new
access/refresh pair from a valid refresh token.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from progress.api.auth import (
    CurrentUser,
    decode_refresh_token,
)
from progress.api.deps import get_config
from progress.api.routes._limiter import limiter
from progress.config.root import CoreConfig
from progress.db.models import User
from progress.utils.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

ConfigDep = Annotated[CoreConfig, Depends(get_config)]


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: int
    username: str
    email: str
    is_active: bool
    is_superuser: bool


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


@router.post("/auth/login", response_model=TokenResponse)
@limiter.limit("30 per minute")
async def login(
    request: Request,
    body: LoginRequest,
    cfg: ConfigDep,
) -> TokenResponse:
    """Authenticate and issue JWTs."""
    user = await User.filter(username=body.username, is_active=True).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )
    secret = cfg.auth.secret_key.get_secret_value()
    return TokenResponse(
        access_token=create_access_token(
            subject=user.username,
            secret_key=secret,
            expires_minutes=cfg.auth.access_token_expire_minutes,
        ),
        refresh_token=create_refresh_token(
            subject=user.username,
            secret_key=secret,
            expires_days=cfg.auth.refresh_token_expire_days,
        ),
    )


@router.post("/auth/refresh", response_model=TokenResponse)
@limiter.limit("30 per minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    cfg: ConfigDep,
) -> TokenResponse:
    """Issue a new access/refresh pair from a valid refresh token."""
    username = decode_refresh_token(body.refresh_token, cfg.auth.secret_key.get_secret_value())
    user = await User.filter(username=username, is_active=True).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    secret = cfg.auth.secret_key.get_secret_value()
    return TokenResponse(
        access_token=create_access_token(
            subject=user.username,
            secret_key=secret,
            expires_minutes=cfg.auth.access_token_expire_minutes,
        ),
        refresh_token=create_refresh_token(
            subject=user.username,
            secret_key=secret,
            expires_days=cfg.auth.refresh_token_expire_days,
        ),
    )


@router.get("/auth/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> UserResponse:
    """Return the authenticated user's profile."""
    return UserResponse.model_validate(current_user)


@router.post("/auth/change-password", response_model=UserResponse)
@limiter.limit("10 per minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    current_user: CurrentUser,
) -> UserResponse:
    """Change the current user's password."""
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    current_user.hashed_password = hash_password(body.new_password)
    await current_user.save(update_fields=["hashed_password", "updated_at"])
    logger.info("user %s changed their password", current_user.username)
    return UserResponse.model_validate(current_user)


__all__ = ["router"]
