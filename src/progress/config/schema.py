"""JSON Schema export for the configuration system.

Merges core schema with each registered integration's schema so the frontend
config editor can render forms server-driven (spec 02, 12).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from progress.config.root import CoreConfig
from progress.integrations.registry import discover_integrations


def get_core_config_schema() -> dict[str, Any]:
    """Return the JSON Schema for the core section (section="core")."""
    schema = CoreConfig.model_json_schema()
    schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
    return schema


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
            schema = config_schema.model_json_schema()
            schema.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
            schemas[name] = schema
    except Exception:
        pass
    return schemas
