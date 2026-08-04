"""Shared Pydantic response models (spec 12).

Per spec 12:
- All responses declare a ``response_model`` (Pydantic) for runtime validation
  + complete OpenAPI schema (the frontend's single source of truth).
- Unified pagination shape: ``{items, page, page_size, total, has_next}``.
- Unified error envelope: ``{"error": {"code", "message", "details"}}``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    """Error envelope payload (spec 12)."""

    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Top-level error envelope: ``{"error": {...}}``."""

    model_config = ConfigDict(extra="forbid")
    error: ErrorDetail


class PaginationMeta(BaseModel):
    """Pagination metadata shared by every list endpoint."""

    model_config = ConfigDict(extra="forbid")
    page: int = Field(ge=1, default=1)
    page_size: int = Field(ge=1, le=100, default=20)
    total: int = Field(ge=0, default=0)
    has_next: bool = False


class PaginatedResponse[T](BaseModel):
    """Unified paginated response shape (spec 12)."""

    model_config = ConfigDict(extra="forbid")
    items: list[T]
    page: int = Field(ge=1, default=1)
    page_size: int = Field(ge=1, le=100, default=20)
    total: int = Field(ge=0, default=0)
    has_next: bool = False


class HealthResponse(BaseModel):
    """Liveness probe response (no auth, no DB hit)."""

    model_config = ConfigDict(extra="forbid")
    status: str = "ok"


class ReadyResponse(BaseModel):
    """Readiness probe response (pings DB)."""

    model_config = ConfigDict(extra="forbid")
    status: str = "ok"
    database: str = "ok"


class VersionResponse(BaseModel):
    """Version info response."""

    model_config = ConfigDict(extra="forbid")
    name: str = "progress"
    version: str = "0.0.1"


class IntegrationSummary(BaseModel):
    """One registered integration in ``GET /api/v1/integrations``."""

    model_config = ConfigDict(extra="forbid")
    name: str
    config_schema: dict[str, Any] = Field(default_factory=dict)


class ReportSummary(BaseModel):
    """Lightweight report representation for list responses."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: int
    report_type: str
    title: str
    commit_hash: str
    previous_commit_hash: str | None = None
    commit_count: int
    markpost_url: str | None = None
    created_at: str


class ReportDetail(BaseModel):
    """Full report including rendered HTML content (spec 12)."""

    model_config = ConfigDict(extra="forbid", from_attributes=True)
    id: int
    report_type: str
    title: str
    commit_hash: str
    previous_commit_hash: str | None = None
    commit_count: int
    markpost_url: str | None = None
    content: str
    rendered_html: str
    created_at: str


class RawMarkdownResponse(BaseModel):
    """Raw markdown response for ``GET /api/v1/reports/{id}/raw``."""

    model_config = ConfigDict(extra="forbid")
    id: int
    report_type: str
    title: str
    markdown: str


class ConfigSectionResponse(BaseModel):
    """Per-section config dump with secrets masked (SecretStr → ``**********``)."""

    model_config = ConfigDict(extra="forbid")
    section: str
    data: dict[str, Any]


class AllConfigResponse(BaseModel):
    """``{section: data}`` map for ``GET /api/v1/config``."""

    model_config = ConfigDict(extra="forbid")
    core: dict[str, Any] = Field(default_factory=dict)
    plugins: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ConfigSchemaResponse(BaseModel):
    """``{section: JSON Schema}`` map for ``GET /api/v1/config/schema``."""

    model_config = ConfigDict(extra="forbid")
    schemas: dict[str, dict[str, Any]]


class ConfigUpdateRequest(BaseModel):
    """Body for ``PUT /api/v1/config/{section}``."""

    model_config = ConfigDict(extra="forbid")
    data: dict[str, Any]


class ConfigReloadResponse(BaseModel):
    """Acknowledgement for ``POST /api/v1/config/reload``."""

    model_config = ConfigDict(extra="forbid")
    status: str = "ok"
    section: str = "core"


class TestChannelResult(BaseModel):
    """Per-channel outcome of a test notification dispatch."""

    model_config = ConfigDict(extra="forbid")
    channel: str
    ok: bool
    error: str | None = None


class TestNotificationResponse(BaseModel):
    """Aggregated outcome of ``POST /api/v1/config/notifications/test``."""

    model_config = ConfigDict(extra="forbid")
    results: list[TestChannelResult]
    summary: str  # "ok" | "partial_failure" | "no_channels"


class LanguageResponse(BaseModel):
    """Configured UI/notifications language for ``GET /api/v1/config/language``.

    The SPA reads this on boot so its initial locale matches the server's
    ``core.language`` (instead of only honouring localStorage / the browser's
    Accept-Language, which left the UI in English even when zh-Hans was
    configured). Returned unmasked — language is not a secret.
    """

    model_config = ConfigDict(extra="forbid")
    language: str


class LanguageUpdateRequest(BaseModel):
    """Body for ``PUT /api/v1/config/language``.

    A dedicated single-field endpoint (rather than ``PUT /api/v1/config/core``)
    so the language switcher can change language atomically without having to
    round-trip the whole (masked) core section.
    """

    model_config = ConfigDict(extra="forbid")
    language: str


__all__ = [
    "AllConfigResponse",
    "ConfigReloadResponse",
    "ConfigSchemaResponse",
    "ConfigSectionResponse",
    "ConfigUpdateRequest",
    "ErrorDetail",
    "ErrorResponse",
    "HealthResponse",
    "IntegrationSummary",
    "LanguageResponse",
    "LanguageUpdateRequest",
    "PaginatedResponse",
    "PaginationMeta",
    "RawMarkdownResponse",
    "ReadyResponse",
    "ReportDetail",
    "ReportSummary",
    "TestChannelResult",
    "TestNotificationResponse",
    "VersionResponse",
]
