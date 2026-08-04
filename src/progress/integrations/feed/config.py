"""Pydantic config schema for the ``feed`` integration (spec 02 / spec feed §3).

Per spec feed §3, the feed integration owns **only** the Miniflux data-source
credentials. Everything else (DB path, timezone, markpost, AI, notification,
observability) is shared core infrastructure (spec 02) and lives in ``[core]``.

Zero-config behaviour: an empty ``base_url`` (the default) degrades the feed
integration to disabled at ``setup`` time — it logs a warning and ``run``
returns an empty :class:`~progress.integrations.base.RunResult`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, SecretStr


class FeedIntegrationConfig(BaseModel):
    """Top-level config for the ``feed`` integration (spec feed §3)."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: SecretStr = SecretStr("")


__all__ = ["FeedIntegrationConfig"]
