"""Pydantic config schema for the ``feed`` integration (spec 02 / spec feed §3).

Per spec feed §3, the feed integration owns **only** the Miniflux data-source
credentials. Everything else (DB path, timezone, markpost, AI, notification,
observability) is shared core infrastructure (spec 02) and lives in ``[core]``.

Zero-config behaviour: an empty ``base_url`` (the default) degrades the feed
integration to disabled at ``setup`` time — it logs a warning and ``run``
returns an empty :class:`~progress.integrations.base.RunResult`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from progress.utils.cron import CronExpression


class FeedIntegrationConfig(BaseModel):
    """Top-level config for the ``feed`` integration (spec feed §3)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "integrations", "ui_order": 120},
    )

    base_url: str = Field(
        default="",
        title="Miniflux Base URL",
        description="Base URL of the Miniflux instance. Leave empty to disable the feed integration.",
        examples=["https://miniflux.example.com"],
    )
    api_key: SecretStr = Field(
        default=SecretStr(""),
        title="Miniflux API Key",
        description="API key for accessing the Miniflux API.",
    )
    schedule_cron: CronExpression = Field(
        default="",
        title="Schedule Override (cron)",
        description="5-field cron expression that schedules only this integration, replacing the global "
        "schedule for it. Leave empty to inherit the global schedule.",
        examples=["0 */4 * * *"],
    )


__all__ = ["FeedIntegrationConfig"]
