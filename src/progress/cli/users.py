"""User management CLI (Typer sub-app, ``progress users <command>``).

Provides Django-``manage.py``-style commands for user administration without a
web UI. Registered as a sub-command group on the main Typer app in
``progress.cli``::

    progress users create alice --superuser
    progress users reset-password alice
    progress users list
    progress users deactivate alice

Each command boots a minimal lifespan (init_db + load config) so it can run
standalone outside the API server. All heavy imports are deferred into the
command bodies to avoid a module-load-time circular import through
``progress.config.root`` (which imports ``progress.cli.notifications``).
"""

from __future__ import annotations

import asyncio
import logging
import secrets

import typer

from progress.config.loader import load_config
from progress.db import close_db, init_db
from progress.db.models import User
from progress.utils.security import hash_password

logger = logging.getLogger(__name__)

users_app = typer.Typer(help="User management commands (create, reset-password, list, deactivate).")


def _run(coro):
    """Run ``coro`` with proper cleanup."""
    try:
        return asyncio.run(coro)
    finally:
        asyncio.run(_close())


async def _close() -> None:

    await close_db()


def _hash_password(plain: str) -> str:
    """Hash ``plain`` (thin wrapper kept for call-site readability)."""
    return hash_password(plain)


@users_app.command("create")
def create_user(
    username: str = typer.Argument(..., help="Username (unique)."),
    password: str = typer.Option("", "--password", "-p", help="Password (random if omitted)."),
    email: str = typer.Option("", "--email", "-e", help="Optional email."),
    superuser: bool = typer.Option(False, "--superuser", "-s", help="Grant superuser privileges."),
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """Create a new user."""

    async def _create() -> None:

        cfg = load_config(config)
        await init_db(cfg.state_home)
        existing = await User.filter(username=username).first()
        if existing is not None:
            typer.echo(f"Error: user {username!r} already exists", err=True)
            raise typer.Exit(code=1)
        if not password:
            generated = secrets.token_urlsafe(16)
            typer.echo(f"Generated password for {username}: {generated}")
            pw = generated
        else:
            pw = password
        await User.create(
            username=username,
            email=email,
            hashed_password=_hash_password(pw),
            is_active=True,
            is_superuser=superuser,
        )
        typer.echo(f"Created user {username!r} (superuser={superuser})")

    _run(_create())


@users_app.command("reset-password")
def reset_password(
    username: str = typer.Argument(..., help="Username to reset."),
    password: str = typer.Option("", "--password", "-p", help="New password (random if omitted)."),
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """Reset a user's password."""

    async def _reset() -> None:

        cfg = load_config(config)
        await init_db(cfg.state_home)
        user = await User.filter(username=username).first()
        if user is None:
            typer.echo(f"Error: user {username!r} not found", err=True)
            raise typer.Exit(code=1)
        if not password:
            generated = secrets.token_urlsafe(16)
            typer.echo(f"Generated password for {username}: {generated}")
            pw = generated
        else:
            pw = password
        user.hashed_password = _hash_password(pw)
        await user.save(update_fields=["hashed_password", "updated_at"])
        typer.echo(f"Reset password for {username!r}")

    _run(_reset())


@users_app.command("list")
def list_users(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """List all users."""

    async def _list() -> None:

        cfg = load_config(config)
        await init_db(cfg.state_home)
        users = await User.all().order_by("id")
        if not users:
            typer.echo("(no users)")
            return
        typer.echo(f"{'ID':>4}  {'USERNAME':<20} {'EMAIL':<30} {'ACTIVE':<7} {'SUPER'}")
        for u in users:
            typer.echo(
                f"{u.id:>4}  {u.username:<20} {u.email or '':<30} "
                f"{'yes' if u.is_active else 'no':<7} {'yes' if u.is_superuser else 'no'}"
            )

    _run(_list())


@users_app.command("deactivate")
def deactivate_user(
    username: str = typer.Argument(..., help="Username to deactivate."),
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """Deactivate a user (set is_active=False; login will be rejected)."""

    async def _deactivate() -> None:

        cfg = load_config(config)
        await init_db(cfg.state_home)
        user = await User.filter(username=username).first()
        if user is None:
            typer.echo(f"Error: user {username!r} not found", err=True)
            raise typer.Exit(code=1)
        user.is_active = False
        await user.save(update_fields=["is_active", "updated_at"])
        typer.echo(f"Deactivated user {username!r}")

    _run(_deactivate())


__all__ = ["users_app"]
