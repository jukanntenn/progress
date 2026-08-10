"""CoreConfig: top-level aggregate root for project configuration.

Per spec 02:
- Ansible class (config.toml, :ro): only ``state_home``.
- Core Web class (DB config table section="core"): user preferences, credentials,
  business tuning. Loaded from DB at runtime, optionally seeded from
  ``config.db.toml``.
- Plugin config (DB config table section=plugin name): each integration owns its
  own Pydantic config model.

All secret fields use ``pydantic.SecretStr`` so ``model_dump_json()`` emits
``**********`` automatically (no hand-written masking).

Domain config models live in their respective packages per spec 02
(Django app-style): ``NotificationConfig`` in ``cli/notifications/``,
``ObservabilityConfig`` in ``observability/``.
"""

from __future__ import annotations

from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings

from progress.cli.notifications.config import NotificationConfig
from progress.observability.config import ObservabilityConfig


class GitHubConfig(BaseModel):
    """GitHub credentials (Web class, user-editable)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "integrations", "ui_order": 10},
    )
    gh_token: SecretStr = Field(
        default=SecretStr(""),
        title="GitHub Access Token",
        description="Personal access token for GitHub API calls. Requires `repo` read scope. "
        "Create one at GitHub Settings → Developer settings → Personal access tokens.",
        examples=["ghp_xxxxxxxxxxxx"],
    )
    proxy: str = Field(
        default="",
        title="HTTP Proxy",
        description="Optional HTTP(S) proxy for reaching GitHub. Leave empty for direct connection.",
        examples=["http://127.0.0.1:7890"],
    )


class AnalysisConfig(BaseModel):
    """Pydantic AI provider/model configuration (Web class).

    ``concurrency`` is the per-integration run concurrency (spec 06). It
    controls how many repos/trackers/types an integration processes in
    parallel; AI calls themselves are still serialized by a global semaphore
    (``AI_CONCURRENCY`` constant in ``cli/ai/agent.py``, spec 02/08).
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "integrations", "ui_order": 20},
    )
    provider: str = Field(
        default="",
        title="AI Provider",
        description="The model provider used for AI analysis.",
        examples=["openai", "deepseek"],
    )
    model: str = Field(
        default="",
        title="AI Model",
        description="Specific model identifier to use for analysis.",
        examples=["gpt-4o", "deepseek-chat"],
        json_schema_extra={"ui_group": "integrations", "ui_order": 40},
    )
    api_key: SecretStr = Field(
        default=SecretStr(""),
        title="AI API Key",
        description="Secret key for authenticating with the AI provider.",
    )
    base_url: str = Field(
        default="",
        title="API Base URL",
        description="Custom API endpoint. Leave empty to use the provider's default.",
        examples=["https://api.openai.com/v1"],
    )
    language: str = Field(
        default="en",
        title="Report Language",
        description="Language the AI uses when generating analysis reports.",
        examples=["en", "zh-Hans"],
    )
    concurrency: int = Field(
        default=1,
        ge=1,
        le=10,
        title="Concurrency",
        description="Number of integrations processed in parallel. Higher values speed up runs "
        "but increase AI resource usage and rate-limit risk. Range 1–10.",
        examples=[1, 2, 3],
    )


class MarkpostConfig(BaseModel):
    """MarkPost publishing target (Web class)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "system", "ui_order": 10},
    )
    enabled: bool = Field(
        default=False,
        title="Publish to MarkPost",
        description="When enabled, reports are published to the configured MarkPost instance.",
    )
    url: SecretStr = Field(
        default=SecretStr(""),
        title="MarkPost URL",
        description="Base URL of the MarkPost publishing endpoint.",
        examples=["https://markpost.example.com"],
    )
    max_batch_size: int = Field(
        default=1_048_576,
        title="Max Batch Size",
        description="Maximum payload size in bytes when publishing to MarkPost.",
        examples=[1_048_576],
    )


class WebConfig(BaseModel):
    """Public-facing web base URL (used for report back-links)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "system", "ui_order": 40},
    )
    base_url: str = Field(
        default="",
        title="Public Web Base URL",
        description="Public-facing base URL of this instance, used for back-links in notifications and RSS.",
        examples=["https://progress.example.com"],
    )


class AuthConfig(BaseModel):
    """Authentication configuration (Web class).

    When ``enabled`` is ``True`` (default), all non-public API endpoints require
    a valid Bearer JWT. ``secret_key`` signs the JWTs; if left empty at startup
    a random key is generated, persisted to the DB config, and used thereafter.
    """

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "system", "ui_order": 50},
    )
    enabled: bool = Field(
        default=True,
        title="Enable Authentication",
        description="When enabled, all non-public API endpoints require a valid Bearer token.",
    )
    secret_key: SecretStr = Field(
        default=SecretStr(""),
        title="JWT Secret Key",
        description="Secret used to sign access and refresh tokens. A random key is generated "
        "on first boot if left empty.",
    )
    access_token_expire_minutes: int = Field(
        default=30,
        ge=1,
        title="Access Token Lifetime",
        description="Lifetime of access tokens in minutes. Range ≥1.",
        examples=[30],
    )
    refresh_token_expire_days: int = Field(
        default=30,
        ge=1,
        title="Refresh Token Lifetime",
        description="Lifetime of refresh tokens in days. Range ≥1.",
        examples=[30],
    )
    initial_admin_username: str = Field(
        default="admin",
        title="Initial Admin Username",
        description="Username of the superuser created on first boot when authentication is "
        "enabled and the users table is empty.",
        examples=["admin"],
    )
    initial_admin_password: SecretStr = Field(
        default=SecretStr(""),
        title="Initial Admin Password",
        description="Password of the initial superuser. A random password is printed to the logs if left empty.",
    )


class CoreConfig(BaseSettings):
    """Top-level aggregate root.

    Per spec 02, uses ``pydantic-settings`` ``BaseSettings`` for proper
    configuration management with env variable overrides and TOML file support.

    Only ``state_home`` is loaded from the Ansible-class file (``config.toml``);
    all other fields are populated from the DB ``config`` table (section="core")
    at runtime, optionally seeded from ``config.db.toml``.
    """

    model_config = ConfigDict(
        extra="forbid",
        env_prefix="PROGRESS_",  # ty:ignore[invalid-key]
        env_nested_delimiter="__",  # ty:ignore[invalid-key]
    )
    state_home: str = "data"
    language: str = Field(
        default="en",
        title="Language",
        description="UI and report language. Changing this also switches the running interface immediately.",
        examples=["en", "zh-Hans"],
        json_schema_extra={"ui_group": "preferences", "ui_order": 10},
    )
    timezone: str = Field(
        default="UTC",
        title="Timezone",
        description="Timezone used for report timestamps and scheduling. Must be an IANA zone identifier.",
        examples=["UTC", "Asia/Shanghai"],
        json_schema_extra={"ui_group": "preferences", "ui_order": 20},
    )
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    markpost: MarkpostConfig = Field(default_factory=MarkpostConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError(f"Invalid timezone: '{v}'")
        return v

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        return _normalize_bcp47(v) if v else v


def _normalize_bcp47(tag: str) -> str:
    """Normalize a language tag to BCP-47 canonical casing.

    Sub-tags are cased per their role: the primary language is lowercased, a
    4-letter script sub-tag is title-cased (``Hans``), and a 2-letter region is
    uppercased. This matches what ``Intl.getCanonicalLocales`` produces in the
    browser (and what i18next uses to key its resource bundles), so the value
    stored in the DB round-trips with the SPA without case-mismatch fallbacks.
    Examples: ``zh-hans``/``ZH-HANS`` → ``zh-Hans``; ``pt-br`` → ``pt-BR``;
    ``en`` → ``en``.
    """
    parts = tag.split("-")
    if not parts:
        return tag
    parts[0] = parts[0].lower()
    for i in range(1, len(parts)):
        sub = parts[i]
        parts[i] = sub.capitalize() if len(sub) == 4 else sub.upper()
    return "-".join(parts)
