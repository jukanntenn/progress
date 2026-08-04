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

    model_config = ConfigDict(extra="forbid")
    gh_token: SecretStr = SecretStr("")
    proxy: str = ""


class AnalysisConfig(BaseModel):
    """Pydantic AI provider/model configuration (Web class).

    ``concurrency`` is the per-integration run concurrency (spec 06). It
    controls how many repos/trackers/types an integration processes in
    parallel; AI calls themselves are still serialized by a global semaphore
    (``AI_CONCURRENCY`` constant in ``cli/ai/agent.py``, spec 02/08).
    """

    model_config = ConfigDict(extra="forbid")
    provider: str = ""
    model: str = ""
    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    language: str = "en"
    concurrency: int = Field(default=1, ge=1)


class MarkpostConfig(BaseModel):
    """MarkPost publishing target (Web class)."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    url: SecretStr = SecretStr("")
    max_batch_size: int = 1_048_576


class WebConfig(BaseModel):
    """Public-facing web base URL (used for report back-links)."""

    model_config = ConfigDict(extra="forbid")
    base_url: str = ""


class AuthConfig(BaseModel):
    """Authentication configuration (Web class).

    When ``enabled`` is ``True`` (default), all non-public API endpoints require
    a valid Bearer JWT. ``secret_key`` signs the JWTs; if left empty at startup
    a random key is generated, persisted to the DB config, and used thereafter.
    """

    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    secret_key: SecretStr = SecretStr("")
    access_token_expire_minutes: int = Field(default=30, ge=1)
    refresh_token_expire_days: int = Field(default=30, ge=1)
    initial_admin_username: str = "admin"
    initial_admin_password: SecretStr = SecretStr("")


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
    language: str = "en"
    timezone: str = "UTC"
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
