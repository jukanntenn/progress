"""JSON Schema export for the configuration system.

Merges core schema with each registered integration's schema so the frontend
config editor can render forms server-driven (spec 02, 12).

The core schema is stripped of system-internal fields (``state_home``,
``auth.secret_key``, ``auth.initial_admin_password``) so they never render in
the Web UI; they remain in the DB and are protected on write by
``progress.db._preserve_internal_fields``.

No ``$schema`` keyword is emitted: the RJSF frontend validates with
``@rjsf/validator-ajv8`` (ajv draft-07); a draft/2020-12 ``$schema`` declaration
would make ajv look up an unregistered meta-schema and fail every compile.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from progress.config.root import CoreConfig
from progress.integrations.registry import discover_integrations

# 编辑可见字段集合（core 段中允许前端编辑的字段）
# state_home / auth.secret_key / auth.initial_admin_password 不在其中
_CORE_EDITABLE_EXCLUDE = {"state_home"}

_AUTH_INTERNAL_FIELDS = ("secret_key", "initial_admin_password")


def get_core_config_schema() -> dict[str, Any]:
    """Return the core section's editable JSON Schema (internal fields stripped)."""
    schema = CoreConfig.model_json_schema()
    for key in _CORE_EDITABLE_EXCLUDE:
        schema.get("properties", {}).pop(key, None)
        required = schema.get("required", [])
        if key in required:
            required.remove(key)
    auth_def_name = _find_def_by_title(schema, "AuthConfig")
    if auth_def_name:
        auth_def = schema["$defs"][auth_def_name]
        for key in _AUTH_INTERNAL_FIELDS:
            auth_def.get("properties", {}).pop(key, None)
            required = auth_def.get("required", [])
            if key in required:
                required.remove(key)
    return schema


def _find_def_by_title(schema: dict[str, Any], title: str) -> str | None:
    for def_name, def_schema in schema.get("$defs", {}).items():
        if isinstance(def_schema, dict) and def_schema.get("title") == title:
            return def_name
    return None


@lru_cache(maxsize=1)
def get_config_json_schema() -> dict[str, dict[str, Any]]:
    """Return ``{section: <JSON Schema>}`` for core + every registered integration.

    Integrations register their config schemas through
    :func:`progress.integrations.registry.discover_integrations`; each
    ``Integration.config_schema`` is a Pydantic model whose
    ``model_json_schema()`` becomes the section schema.
    """
    schemas: dict[str, dict[str, Any]] = {"core": get_core_config_schema()}
    try:
        for name, integration_cls in discover_integrations().items():
            config_schema = getattr(integration_cls, "config_schema", None)
            if config_schema is None:
                continue
            schemas[name] = config_schema.model_json_schema()
    except Exception:
        pass
    return schemas
