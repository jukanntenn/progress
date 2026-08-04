"""Observability configuration models (spec 02).

Per spec 02, domain config models live in their respective packages:
- ``BugsinkConfig`` — Bugsink (Sentry-compatible) error tracking DSN
- ``ObservabilityConfig`` — observability targets aggregation

Both are Web-class (DB ``config`` table, section="core" sub-tree).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class BugsinkConfig(BaseModel):
    """Bugsink (Sentry-compatible) error tracking DSN (Web class)."""

    model_config = ConfigDict(extra="forbid")
    dsn: SecretStr = SecretStr("")
    environment: str = "production"


class ObservabilityConfig(BaseModel):
    """Observability targets (Bugsink DSN is Web-class; OTel exporter is a code constant)."""

    model_config = ConfigDict(extra="forbid")
    bugsink: BugsinkConfig = Field(default_factory=BugsinkConfig)


__all__ = ["BugsinkConfig", "ObservabilityConfig"]
