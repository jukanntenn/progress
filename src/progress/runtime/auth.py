"""Auth entry + bootstrap: JWT secret + initial superuser (PRFC phase 1/3).

``bootstrap_auth`` moved here from ``progress.api.auth_bootstrap`` — it has
no FastAPI dependency (db + config + security only), and the runtime layer
must not import the api layer (import-linter contract 3). It mutates the
merged config in place (generating and persisting a secret when empty), so
the webserver entry injects the ``authReady`` marker this module's entry
provides — the one ordering an in-place mutation cannot express through
``config`` alone. Sunk into the base tree (cron-only deployments bootstrap
on first run too).
"""

from __future__ import annotations

import logging
import secrets

from pydantic import BaseModel, SecretStr

from progress.config.root import CoreConfig
from progress.db import _dump_plaintext, get_config, set_config
from progress.db.models import User
from progress.kernel import Definition, Entry
from progress.utils.security import hash_password

logger = logging.getLogger(__name__)


class AuthReady(Definition):
    service_name = "authReady"


def make_auth_entry() -> Entry:
    async def _apply(ctx, config) -> None:
        cfg = ctx.config
        await bootstrap_auth(cfg)
        ctx.provide(AuthReady, True)

    return Entry(id="auth", plugin=_apply, inject=["config"])


async def bootstrap_auth(cfg: CoreConfig) -> CoreConfig:
    """Ensure a JWT secret exists and seed the initial admin if needed.

    Returns the (possibly updated) config so the caller can store it back on
    ``app.state.cfg``. Safe to call on every startup — both steps are no-ops
    once the secret + admin exist.
    """
    cfg = await _ensure_secret_key(cfg)
    if cfg.auth.enabled:
        await _ensure_admin_user(cfg)
    return cfg


async def _ensure_secret_key(cfg: CoreConfig) -> CoreConfig:
    """Generate + persist a secret key if none is configured."""
    if cfg.auth.secret_key.get_secret_value():
        return cfg
    generated = secrets.token_urlsafe(32)
    logger.warning("auth.secret_key was empty; generated a random key and persisted it to the DB config")
    cfg.auth.secret_key = SecretStr(generated)
    await _persist_core_field(cfg, "auth", cfg.auth)
    return cfg


async def _ensure_admin_user(cfg: CoreConfig) -> None:
    """Create the initial superuser when the users table is empty."""
    if await User.all().count() > 0:
        return
    username = cfg.auth.initial_admin_username or "admin"
    password = cfg.auth.initial_admin_password.get_secret_value()
    generated = False
    if not password:
        password = secrets.token_urlsafe(16)
        generated = True
    await User.create(
        username=username,
        hashed_password=hash_password(password),
        is_active=True,
        is_superuser=True,
    )
    if generated:
        logger.warning(
            "created initial admin user %r with a randomly generated password: %s",
            username,
            password,
        )
        logger.warning(
            "this password is shown only once; change it via the API or "
            "`progress users reset-password` after first login"
        )
    else:
        logger.info("created initial admin user %r from configured credentials", username)


async def _persist_core_field(cfg: CoreConfig, field: str, sub_model: BaseModel) -> None:
    """Merge a sub-config's new value (plaintext) back into the DB core section."""
    raw = await get_config("core")
    if not isinstance(raw, dict):
        raw = {}
    raw[field] = _dump_plaintext(sub_model)
    await set_config("core", raw)


__all__ = ["bootstrap_auth"]
