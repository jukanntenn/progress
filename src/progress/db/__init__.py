"""Database initialization, connection management, and config-table CRUD.

Per spec 03:
- Use tortoise-orm's built-in migrations (per-app ``migrations/`` directories).
- ``init_db`` initializes the connection and applies migrations.
- Config table read/write API (spec 02) is implemented here on top of the
  ``Config`` tortoise model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from tortoise import Tortoise
from tortoise.connection import get_connection
from tortoise.migrations.executor import MigrationExecutor, MigrationTarget

from progress.db.models.config import Config
from progress.db.tortoise_config import build_db_url, build_tortoise_config
from progress.errors import ConfigException
from progress.integrations.registry import discover_integrations
from progress.observability import record_business_event

logger = logging.getLogger(__name__)


async def init_db(state_home: str, *, run_migrations: bool = True) -> None:
    """Initialize the DB connection and apply migrations.

    The DB file lives at ``<state_home>/progress.db`` (spec 02 derived path).
    """
    db_url = build_db_url(state_home)
    Path(state_home).mkdir(parents=True, exist_ok=True)
    config = build_tortoise_config(db_url)
    await Tortoise.init(config=config, _enable_global_fallback=True)
    logger.info("Database initialized: %s", state_home)
    if run_migrations:
        await _apply_migrations(config)


async def _apply_migrations(config: dict[str, Any]) -> None:
    """Apply pending tortoise migrations using the existing connection.

    Per-migration error handling: if a migration fails with "already exists"
    or "duplicate column" (bootstrap case where tables were created outside
    the migration system), it is fake-applied (marked as applied without
    running) so subsequent migrations can proceed. All other errors are logged
    and recorded as metrics but never raised - the program degrades, never
    crashes (spec 03 invariant).
    """

    apps_cfg = config.get("apps", {})
    for app_label, app_config in apps_cfg.items():
        connection_name = app_config.get("default_connection", "default")
        connection = get_connection(connection_name)
        if connection is None:
            logger.warning(
                "no connection '%s' for app '%s'; skipping migrations",
                connection_name,
                app_label,
            )
            continue

        executor = MigrationExecutor(connection, {app_label: app_config})
        try:
            await executor.loader.build_graph()
            await executor.recorder.ensure_schema(executor._schema_editor(atomic=False))  # noqa: SLF001
            applied = set(await executor.recorder.applied_migrations())

            migration_names = sorted(executor.loader.graph.nodes)
            for mkey in migration_names:
                name = mkey.name
                already = any(k.app_label == app_label and k.name == name for k in applied)
                if already:
                    continue

                target = [MigrationTarget(app_label=app_label, name=name)]
                try:
                    await executor.migrate(target)
                    logger.info("migration %s/%s applied", app_label, name)
                    record_business_event(
                        "progress.db.migration_applied",
                        attributes={"app": app_label, "name": name},
                    )
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg or "duplicate column" in msg:
                        logger.info(
                            "migration %s/%s already in effect; fake-applying",
                            app_label,
                            name,
                        )
                        await executor.migrate(target, fake=True)
                        record_business_event(
                            "progress.db.migration_bootstrap",
                            attributes={"app": app_label, "name": name},
                        )
                    else:
                        logger.warning(
                            "migration %s/%s failed: %s; continuing",
                            app_label,
                            name,
                            e,
                        )
                        record_business_event(
                            "progress.db.migration_failed",
                            attributes={"app": app_label, "name": name, "error": str(e)[:200]},
                        )
        except Exception as e:
            logger.warning(
                "migration setup failed for app %s: %s; continuing",
                app_label,
                e,
            )
            record_business_event(
                "progress.db.migration_failed",
                attributes={"app": app_label, "name": "setup", "error": str(e)[:200]},
            )


async def close_db() -> None:
    """Close all DB connections."""
    await Tortoise.close_connections()
    logger.info("Database connections closed")


async def get_config(section: str) -> dict[str, Any]:
    """Read a config section's payload. Returns ``{}`` if absent."""

    row = await Config.get_or_none(section=section)
    if row is None:
        return {}
    data = row.data
    return dict(data) if isinstance(data, dict) else {}


async def set_config(section: str, data: dict[str, Any]) -> None:
    """Upsert a config section's payload after schema validation (spec 02).

    Per spec 02, when a submitted SecretStr field equals the mask sentinel
    ``"**********"`` (i.e. the frontend round-tripped the masked value
    unchanged), the real value already stored in the DB is preserved instead
    of being overwritten with the literal mask string.
    """

    existing = await Config.get_or_none(section=section)
    existing_data = existing.data if existing is not None else {}
    if isinstance(existing_data, dict):
        data = _preserve_masked_secrets(data, existing_data)
    payload = _validate_section(section, data)
    await Config.update_or_create(section=section, defaults={"data": payload})


_SECRET_MASK_VALUES = frozenset({"**********", "********"})


def _unmask_real_secrets(validated: dict[str, Any], original: dict[str, Any]) -> dict[str, Any]:
    """Replace masked secret values with real ones from the original data.

    After ``model_validate`` + ``model_dump(mode='json')``, SecretStr fields
    are masked to ``'**********'``.  If the caller supplied the real value in
    ``original``, restore it so the DB stores the actual credential.
    """
    out: dict[str, Any] = {}
    for key, val in validated.items():
        orig = original.get(key)
        if (
            isinstance(val, str)
            and val in _SECRET_MASK_VALUES
            and isinstance(orig, str)
            and orig not in _SECRET_MASK_VALUES
        ):
            out[key] = orig
        elif isinstance(val, dict) and isinstance(orig, dict):
            out[key] = _unmask_real_secrets(val, orig)
        else:
            out[key] = val
    return out


def _preserve_masked_secrets(submitted: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """Recursively keep existing values where the submit sent a mask sentinel.

    Walks ``submitted`` alongside ``existing``. For any key whose submitted
    value is a known SecretStr mask (``"**********"``), the existing value
    is substituted in. Nested dicts (e.g. ``[github]``, ``[analysis]``) are
    recursed so secrets one level down are also preserved. Lists of dicts
    (e.g. ``notification.channels``) are merged element-wise by position so
    a channel that round-tripped its masked ``password`` keeps the real one.
    """
    out: dict[str, Any] = {}
    for key, new_val in submitted.items():
        old_val = existing.get(key)
        if isinstance(new_val, dict) and isinstance(old_val, dict):
            out[key] = _preserve_masked_secrets(new_val, old_val)
        elif isinstance(new_val, list) and isinstance(old_val, list):
            out[key] = _merge_list_with_existing(new_val, old_val)
        elif isinstance(new_val, str) and new_val in _SECRET_MASK_VALUES and old_val is not None:
            out[key] = old_val
        else:
            out[key] = new_val
    return out


def _merge_list_with_existing(new_list: list[Any], old_list: list[Any]) -> list[Any]:
    """Merge a submitted list against the existing one, preserving masked secrets.

    The submitted list is the source of truth for length and ordering (so
    adding/removing list items works as a normal config edit). For elements
    that exist positionally in both lists and are dicts, we recurse so any
    masked SecretStr field inside (e.g. ``channels[0].password``) is preserved
    from the existing row. Elements beyond the old list's length pass through
    unchanged.
    """
    merged: list[Any] = []
    for idx, new_item in enumerate(new_list):
        if idx < len(old_list):
            old_item = old_list[idx]
            if isinstance(new_item, dict) and isinstance(old_item, dict):
                merged.append(_preserve_masked_secrets(new_item, old_item))
            else:
                merged.append(new_item)
        else:
            merged.append(new_item)
    return merged


async def get_all_config() -> dict[str, dict[str, Any]]:
    """Read every config section as ``{section: data}``."""

    out: dict[str, dict[str, Any]] = {}
    async for row in Config.all():
        data = row.data
        out[row.section] = dict(data) if isinstance(data, dict) else {}
    return out


def _validate_section(section: str, data: dict[str, Any]) -> dict[str, Any]:
    """Validate ``data`` against the section's registered JSON Schema."""
    if not isinstance(data, dict):
        raise ConfigException(f"config section '{section}' payload must be a JSON object")
    if section == "core":
        return data
    try:
        integration_cls = discover_integrations().get(section)
    except Exception:
        integration_cls = None
    if integration_cls is None:
        return data
    config_schema = getattr(integration_cls, "config_schema", None)
    if config_schema is None:
        return data
    try:
        validated = config_schema.model_validate(data)
    except Exception as e:
        raise ConfigException(f"invalid config for section '{section}': {e}") from e
    return _unmask_real_secrets(validated.model_dump(mode="json"), data)


__all__ = [
    "build_db_url",
    "build_tortoise_config",
    "close_db",
    "get_all_config",
    "get_config",
    "init_db",
    "set_config",
]
