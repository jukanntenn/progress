"""Database-backed application configuration store.

The editable app config lives in a single versioned JSON blob (the
``app_config`` table, row id = 1). The TOML file is a one-time seed plus the
provider of infra settings (``data_dir`` / ``workspace_dir``); after the first
run the blob is the sole source of truth for app config. Writes use optimistic
locking via the ``version`` column so concurrent writers (web UI, CLI, Ansible
re-deploy) cannot silently overwrite each other.
"""

from __future__ import annotations

import json
import logging
from copy import deepcopy
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .config import Config
from .db.models import AppConfig
from .errors import ConfigException, ProgressException

logger = logging.getLogger(__name__)

UTC = ZoneInfo("UTC")

APP_CONFIG_ID = 1
CURRENT_SCHEMA_VERSION = 2
SECRET_MASK = "********"
INFRA_FIELDS = ("data_dir", "workspace_dir")
EXCLUDED_FROM_BLOB = ("data_dir", "workspace_dir", "repos", "owners")


class ConfigVersionConflict(ConfigException):
    """Raised when a config write is rejected because the version is stale."""


def get_config_json_schema() -> dict:
    """JSON Schema for the editable app config.

    Infra fields (data_dir/workspace_dir) and table-backed lists (repos/owners)
    are excluded: they are not stored in or edited through the blob.
    """
    schema = deepcopy(Config.model_json_schema())
    props = schema.setdefault("properties", {})
    for field in EXCLUDED_FROM_BLOB:
        props.pop(field, None)
    required = schema.get("required")
    if isinstance(required, list):
        schema["required"] = [r for r in required if r not in EXCLUDED_FROM_BLOB]
    schema["schemaVersion"] = CURRENT_SCHEMA_VERSION
    return schema


def _config_from_dict(data: dict) -> Config:
    """Validate ``data`` and build a Config from the dict alone (no env/file)."""

    class _DictConfig(Config):
        model_config = SettingsConfigDict(
            env_prefix="PROGRESS_", env_nested_delimiter="__", extra="ignore"
        )

        @classmethod
        def settings_customise_sources(
            cls,
            settings_cls: type[BaseSettings],
            init_settings: PydanticBaseSettingsSource,
            env_settings: PydanticBaseSettingsSource,
            dotenv_settings: PydanticBaseSettingsSource,
            file_secret_settings: PydanticBaseSettingsSource,
        ) -> tuple[PydanticBaseSettingsSource, ...]:
            return (init_settings,)

    return _DictConfig(**data)


def _load_row() -> AppConfig | None:
    return AppConfig.get_or_none(AppConfig.id == APP_CONFIG_ID)


def is_seeded() -> bool:
    return _load_row() is not None


def load_app_config() -> tuple[dict, int] | None:
    """Return ``(data_dict, version)`` or ``None`` when not yet seeded."""
    row = _load_row()
    if row is None:
        return None
    try:
        data = json.loads(row.data) if row.data else {}
    except json.JSONDecodeError:
        logger.warning("App config blob is corrupt; treating as unseeded")
        return None
    return data, row.version


def _strip_excluded(data: dict) -> dict:
    """Drop keys that do not belong in the blob (infra + table-backed lists)."""
    return {k: v for k, v in data.items() if k not in EXCLUDED_FROM_BLOB}


def migrate_blob_schema() -> None:
    """One-time migration of an existing blob to the current schema version.

    P1 blobs stored ``repos``/``owners`` inline; P2 moves them to their tables,
    so any inline copies are stripped here. Idempotent.
    """
    row = _load_row()
    if row is None or row.schema_version >= CURRENT_SCHEMA_VERSION:
        return
    data = json.loads(row.data) if row.data else {}
    data = _strip_excluded(data)
    row.data = json.dumps(data)
    row.schema_version = CURRENT_SCHEMA_VERSION
    row.updated_at = datetime.now(UTC)
    row.save()
    logger.info(
        "Migrated app config blob to schema version %d (stripped inline repos/owners)",
        CURRENT_SCHEMA_VERSION,
    )


def import_app_config(data: dict) -> int:
    """Replace the blob with ``data`` (explicit file -> DB action).

    Validates, then upserts the blob, bumping the version so concurrent UI
    editors are forced to refresh. Returns the new version.
    """
    payload = _strip_excluded(data)
    validate_config_dict(payload)
    row = _load_row()
    if row is None:
        AppConfig.create(
            id=APP_CONFIG_ID,
            data=json.dumps(payload),
            version=1,
            schema_version=CURRENT_SCHEMA_VERSION,
        )
        logger.info("Imported application config (new blob, version 1)")
        return 1
    new_version = row.version + 1
    AppConfig.update(
        data=json.dumps(payload),
        version=new_version,
        schema_version=CURRENT_SCHEMA_VERSION,
        updated_at=datetime.now(UTC),
    ).where(AppConfig.id == APP_CONFIG_ID).execute()
    logger.info("Imported application config (overwrote blob, version %d)", new_version)
    return new_version


def seed_app_config_if_needed(seed_data: dict) -> bool:
    """One-shot seed of the blob from the file config.

    Returns True when a row was created, False when the blob was already seeded.
    """
    if _load_row() is not None:
        return False
    seed = _strip_excluded(seed_data)
    AppConfig.create(
        id=APP_CONFIG_ID,
        data=json.dumps(seed),
        version=1,
        schema_version=CURRENT_SCHEMA_VERSION,
    )
    logger.info("Seeded application config from file (%d top-level keys)", len(seed))
    return True


def build_runtime_config(blob_data: dict, infra: dict) -> Config:
    """Assemble a runtime Config from the blob plus infra fields."""
    merged = _strip_excluded(blob_data)
    for field in INFRA_FIELDS:
        if field in infra:
            merged[field] = infra[field]
    return _config_from_dict(merged)


def seed_lists_if_needed(file_cfg: Config) -> None:
    """One-shot import of file repos/owners into their tables (fresh deploy).

    ``repos`` and ``owners`` live in the ``repositories``/``github_owners``
    tables, not the blob. On a fresh deploy (empty tables) they are seeded from
    the file config; once populated the tables are managed via the web UI and
    this is a no-op.
    """
    from .contrib.repo.models import GitHubOwner
    from .contrib.repo.owner import replace_owners
    from .contrib.repo.repository import replace_repositories
    from .db.models import Repository

    if file_cfg.repos and Repository.select().count() == 0:
        result = replace_repositories(file_cfg.repos, file_cfg.github.protocol)
        logger.info("Seeded repositories from file: %s", result)
    if file_cfg.owners and GitHubOwner.select().count() == 0:
        result = replace_owners(file_cfg.owners)
        logger.info("Seeded owners from file: %s", result)


# --- schema-driven secret handling ----------------------------------------


def _resolve_ref(schema: dict, root: dict) -> dict:
    ref = schema.get("$ref")
    if not ref:
        return schema
    node = root
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node


def _branch_for_value(value: Any, item_schema: dict, root: dict) -> dict | None:
    """Resolve the matching oneOf branch for a discriminated-union value."""
    discriminator = item_schema.get("discriminator")
    one_of = item_schema.get("oneOf") or item_schema.get("anyOf") or []
    if discriminator and isinstance(value, dict):
        prop = discriminator.get("propertyName")
        mapping = discriminator.get("mapping", {})
        key = value.get(prop)
        if key in mapping:
            return _resolve_ref({"$ref": mapping[key]}, root)
    for branch in one_of:
        resolved = _resolve_ref(branch, root)
        if isinstance(value, dict):
            props = resolved.get("properties", {})
            for pname, pschema in props.items():
                if "const" in pschema and value.get(pname) == pschema["const"]:
                    return resolved
    return None


def _is_secret(field_schema: dict) -> bool:
    return (
        field_schema.get("writeOnly") is True
        or field_schema.get("format") == "password"
    )


def _mask_secrets(value: Any, schema: dict, root: dict) -> Any:
    schema = _resolve_ref(schema, root)
    if isinstance(value, dict) and (schema.get("oneOf") or schema.get("anyOf")):
        branch = _branch_for_value(value, schema, root)
        if branch is not None:
            schema = branch
    if schema.get("type") == "object" and isinstance(value, dict):
        props = schema.get("properties", {})
        return {k: _mask_secrets(v, props.get(k, {}), root) for k, v in value.items()}
    if schema.get("type") == "array" and isinstance(value, list):
        items = schema.get("items", {})
        return [_mask_secrets(elem, items, root) for elem in value]
    if _is_secret(schema) and isinstance(value, str) and value:
        return SECRET_MASK
    return value


def mask_secrets(data: dict) -> dict:
    """Return a copy of ``data`` with every secret field replaced by the mask."""
    schema = get_config_json_schema()
    return _mask_secrets(data, schema, schema)


def _merge_secret_placeholders(submitted: dict, stored: dict) -> dict:
    """Restore stored secret values where the submission kept the mask.

    Walks the submitted and stored trees in parallel (by object key / array
    position). Where a submitted secret equals :data:`SECRET_MASK`, the stored
    value is kept so unchanged secrets survive a round-trip through the masked
    GET without forcing the user to re-enter them.
    """
    schema = get_config_json_schema()

    def merge(sub: Any, sto: Any, node_schema: dict) -> Any:
        node_schema = _resolve_ref(node_schema, schema)
        if (
            node_schema.get("type") == "object"
            and isinstance(sub, dict)
            and isinstance(sto, dict)
        ):
            props = node_schema.get("properties", {})
            return {k: merge(sub.get(k), sto.get(k), props.get(k, {})) for k in sub}
        if (
            node_schema.get("type") == "array"
            and isinstance(sub, list)
            and isinstance(sto, list)
        ):
            items = node_schema.get("items", {})
            merged_list: list[Any] = []
            for idx, elem in enumerate(sub):
                sto_elem = sto[idx] if idx < len(sto) else None
                branch = items
                if isinstance(elem, dict):
                    resolved = _branch_for_value(elem, items, schema) or items
                    branch = resolved
                merged_list.append(merge(elem, sto_elem, branch))
            return merged_list
        if _is_secret(node_schema) and sub == SECRET_MASK:
            return sto
        return sub

    return merge(submitted, stored, schema)


def _format_validation_error(e: ValidationError) -> str:
    lines = ["Configuration validation failed:"]
    for error in e.errors():
        loc = " -> ".join(str(item) for item in error.get("loc", []))
        msg = error.get("msg", "")
        lines.append(f"  - {loc}: {msg}" if loc else f"  - {msg}")
    return "\n".join(lines)


def validate_config_dict(data: dict) -> None:
    """Validate a config dict; raises :class:`ConfigException` on failure."""
    try:
        _config_from_dict(data)
    except ValidationError as e:
        raise ConfigException(_format_validation_error(e)) from e


def validate_app_config(data: dict) -> None:
    """Validate ``data`` the way :func:`save_app_config` would.

    Masked secret placeholders (:data:`SECRET_MASK`) are merged back from
    the stored blob first, so a config that round-tripped through a masked
    GET validates exactly like an actual save. The web UI sends masked
    secrets back on save, so its pre-save validation must match. Raises
    :class:`ConfigException` on failure.
    """
    stored = load_app_config()
    stored_data = stored[0] if stored is not None else {}
    merged = _merge_secret_placeholders(_strip_excluded(data), stored_data)
    validate_config_dict(merged)


def save_app_config(data: dict, expected_version: int) -> tuple[dict, int]:
    """Validate and persist ``data`` under optimistic locking.

    Returns ``(merged_data, new_version)``. Raises :class:`ConfigVersionConflict`
    on a stale version, or :class:`ConfigException` on validation failure.
    """
    row = _load_row()
    if row is None:
        raise ConfigException("Application config has not been seeded")
    stored = json.loads(row.data) if row.data else {}
    merged = _merge_secret_placeholders(_strip_excluded(data), stored)
    validate_config_dict(merged)

    updated = (
        AppConfig.update(
            data=json.dumps(merged),
            version=expected_version + 1,
            schema_version=CURRENT_SCHEMA_VERSION,
            updated_at=datetime.now(UTC),
        )
        .where(
            AppConfig.id == APP_CONFIG_ID,
            AppConfig.version == expected_version,
        )
        .execute()
    )
    if updated == 0:
        current = _load_row()
        current_version = current.version if current else None
        raise ConfigVersionConflict(
            f"Config was modified by another writer "
            f"(expected version {expected_version}, current {current_version}). "
            f"Refresh and try again."
        )
    logger.info(
        "Saved application config (version %d -> %d)",
        expected_version,
        expected_version + 1,
    )
    return merged, expected_version + 1


__all__ = [
    "APP_CONFIG_ID",
    "CURRENT_SCHEMA_VERSION",
    "SECRET_MASK",
    "ConfigVersionConflict",
    "ProgressException",
    "build_runtime_config",
    "get_config_json_schema",
    "import_app_config",
    "is_seeded",
    "load_app_config",
    "mask_secrets",
    "migrate_blob_schema",
    "save_app_config",
    "seed_lists_if_needed",
    "seed_app_config_if_needed",
    "validate_app_config",
    "validate_config_dict",
]
