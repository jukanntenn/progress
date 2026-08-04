"""Tortoise ORM configuration shared by CLI, runtime, and migration CLI.

Per spec 03, CLI ``Tortoise.init`` and the tortoise migration CLI must share the
same modules list so live schema and migrations never drift.

``TORTOISE_ORM`` is exposed as a module-level dict for the tortoise CLI
(``-c progress.db.tortoise_config.TORTOISE_ORM``). It is built lazily on first
access via :func:`__getattr__` to avoid a circular import: building it calls
:func:`discover_integrations`, which imports integration packages, which import
from ``progress.db``. If we built it at module load time,
``progress.db.__init__`` would still be initializing and the integration
imports would fail.
"""

from __future__ import annotations

import pathlib
from typing import Any

from progress.integrations.registry import discover_integrations

APP_LABEL = "core"


def build_tortoise_config(db_url: str) -> dict[str, Any]:
    """Build a TORTOISE_ORM dict for the given SQLite URL.

    Per spec 03, each app (core + each integration) gets its own app label
    with its own migrations directory.  This ensures migrations never drift
    between CLI and runtime.

    The ``migrations`` key points tortoise's ``MigrationLoader`` at our
    committed migration files. Without it the loader treats the app as
    "unmigrated" and silently skips applying migration files.
    """

    apps: dict[str, Any] = {
        APP_LABEL: {
            "models": ["progress.db.models"],
            "default_connection": "default",
            "migrations": "progress.db.migrations",
        }
    }

    for name, integration_cls in discover_integrations().items():
        models_path = getattr(integration_cls, "models_module", None)
        if models_path is None:
            models_path = f"progress.integrations.{name}.models"
        migrations_path = f"progress.integrations.{name}.migrations"
        apps[name] = {
            "models": [models_path],
            "default_connection": "default",
            "migrations": migrations_path,
        }

    return {
        "connections": {"default": db_url},
        "apps": apps,
        "use_tz": True,
        "timezone": "UTC",
    }


def build_db_url(state_home: str) -> str:
    """Build the SQLite DB URL with hardening pragmas (spec 03)."""

    db_path = pathlib.Path(state_home) / "progress.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite://{db_path}?journal_mode=WAL&synchronous=NORMAL&busy_timeout=5000&foreign_keys=ON&cache_size=-64000"


_CACHED_TORTOISE_ORM: dict[str, Any] | None = None


def _get_tortoise_orm() -> dict[str, Any]:
    """Build (and cache) the default TORTOISE_ORM dict for the tortoise CLI.

    The CLI uses ``-c progress.db.tortoise_config.TORTOISE_ORM``; this default
    points at ``<state_home>/data`` which is only useful for makemigrations
    against the development DB. Runtime code uses :func:`build_tortoise_config`
    with the actual ``state_home``.
    """
    global _CACHED_TORTOISE_ORM
    if _CACHED_TORTOISE_ORM is None:
        _CACHED_TORTOISE_ORM = build_tortoise_config(build_db_url("data"))
    return _CACHED_TORTOISE_ORM


def __getattr__(name: str) -> Any:
    """Lazy attribute access so ``TORTOISE_ORM`` is built on demand (PEP 562)."""
    if name == "TORTOISE_ORM":
        return _get_tortoise_orm()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "APP_LABEL",
    "TORTOISE_ORM",  # noqa: F822 - dynamically exposed via __getattr__ (PEP 562)
    "build_db_url",
    "build_tortoise_config",
]
