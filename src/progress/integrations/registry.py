"""Integration registry: ``@register`` decorator + entry_points discovery.

Per spec 06:
- Built-in integrations (``repo``/``changelog``/``proposal``) register
  themselves via ``@register`` when their package is imported.
- Third-party integrations declare ``[project.entry-points."progress.integrations"]``
  in their ``pyproject.toml`` and are discovered via ``importlib.metadata``.

The :func:`discover_integrations` function ensures built-in integration
packages are imported on first call so their ``@register`` decorators run,
then layers any third-party entries on top.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import logging
from typing import Any

logger = logging.getLogger(__name__)

_REGISTRY: dict[str, Any] = {}

_BUILTIN_INTEGRATIONS: tuple[str, ...] = (
    "progress.integrations.repo",
    "progress.integrations.changelog",
    "progress.integrations.proposal",
    "progress.integrations.feed",
)

_discovered: bool = False


def register(name: str):
    """Decorator: register an integration class under ``name``."""

    def deco(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return deco


def _import_builtins() -> None:
    """Import each built-in integration package so ``@register`` runs.

    Failures are logged but do not abort discovery: a single broken
    integration should not prevent the rest from loading.
    """
    for dotted in _BUILTIN_INTEGRATIONS:
        try:
            importlib.import_module(dotted)
        except ImportError as e:
            logger.debug("skipping integration %s: %s", dotted, e)


def discover_integrations() -> dict[str, Any]:
    """Return ``{name: integration_class}`` for all discoverable integrations.

    Built-ins are imported on first call (so ``@register`` runs). Third-party
    integrations are layered on top via ``importlib.metadata.entry_points``.
    """
    global _discovered
    if not _discovered:
        _import_builtins()
        _discovered = True

    result = dict(_REGISTRY)
    try:
        eps = importlib.metadata.entry_points(group="progress.integrations")
    except Exception:
        eps = []
    for ep in eps:
        if ep.name in result:
            continue
        try:
            result[ep.name] = ep.load()
        except Exception as e:
            logger.warning("failed to load integration entry-point %s: %s", ep.name, e)
    return result


def reset_registry() -> None:
    """Clear the registry and discovery cache. For tests only."""
    global _discovered
    _REGISTRY.clear()
    _discovered = False


__all__ = ["discover_integrations", "register", "reset_registry"]
