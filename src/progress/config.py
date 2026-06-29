"""Configuration file loading and validation."""

import logging
import re
from enum import Enum
from pathlib import Path
from typing import List, Literal
from zoneinfo import ZoneInfo, available_timezones

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from .consts import REPO_URL_PATTERNS, WORKSPACE_DIR_DEFAULT
from .enums import Protocol
from .errors import ConfigException
from .notification.config import NotificationConfig

logger = logging.getLogger(__name__)


class MarkpostConfig(BaseModel):
    """Markpost configuration."""

    enabled: bool = Field(
        default=False,
        description="Enable Markpost uploads. When enabled, markpost.url must be set.",
    )
    url: HttpUrl | None = Field(
        default=None,
        description="Markpost publish URL including the post key.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    timeout: int = Field(
        default=30,
        ge=1,
        description="HTTP request timeout in seconds for Markpost API calls.",
    )
    max_batch_size: int = Field(
        default=1048576,
        gt=0,
        description=(
            "Maximum MarkPost body size in bytes. Reports exceeding this are split "
            "into batches, or replaced with a WebUI stub when even a single batch is "
            "too large. Set to the MarkPost service's real body limit."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def default_enabled(cls, values):
        if not isinstance(values, dict):
            return values

        if "enabled" not in values:
            values["enabled"] = bool(values.get("url"))
        return values

    @model_validator(mode="after")
    def validate_markpost_config(self) -> "MarkpostConfig":
        if not self.enabled:
            return self

        if self.url is None:
            raise ValueError("markpost.url is required when markpost.enabled is true")
        return self


class GitHubConfig(BaseModel):
    """GitHub configuration."""

    gh_token: str = Field(
        description="GitHub personal access token (PAT).",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    protocol: Protocol = Field(
        default=Protocol.HTTPS, description="Git clone protocol: 'https' or 'ssh'."
    )
    proxy: str = Field(
        default="", description="HTTP/HTTPS/SOCKS5 proxy URL; empty disables proxy."
    )
    git_timeout: int = Field(
        default=300, ge=1, description="Timeout in seconds for git CLI commands."
    )
    gh_timeout: int = Field(
        default=300,
        ge=1,
        description="Timeout in seconds for GitHub CLI (gh) commands.",
    )


class AnalysisConfig(BaseModel):
    """AI analysis configuration."""

    provider: str = Field(
        default="claude_code",
        description="Analyzer provider: 'claude_code', 'codex', or 'truncate'.",
    )
    max_diff_length: int = Field(
        default=100000, gt=0, description="Max characters of diff sent to the analyzer."
    )
    truncate_chars: int = Field(
        default=200,
        ge=1,
        description="Characters retained when provider is 'truncate'.",
    )
    concurrency: int = Field(
        default=1, ge=1, description="Number of concurrent analysis tasks."
    )
    timeout: int = Field(
        default=600,
        ge=1,
        description="Timeout in seconds for a single analysis call (per attempt).",
    )
    retries: int = Field(
        default=3,
        ge=1,
        description="Total attempts per call including the first; 1 disables retry.",
    )
    retry_delay: int = Field(
        default=5,
        ge=1,
        description="Initial retry delay in seconds; doubles each retry (cap 60s).",
    )
    language: str = Field(
        default="en", description="Output language for AI analysis results."
    )
    first_run_lookback_commits: int = Field(
        default=3,
        ge=1,
        description="Commits analyzed on the first run of a repository.",
    )


class RepositoryConfig(BaseModel):
    """Repository configuration."""

    url: str = Field(
        description="Repository id: 'owner/repo', 'https://...', or 'git@...'."
    )
    branch: str = Field(default="main", description="Branch to track.")
    enabled: bool = Field(
        default=True, description="Set false to temporarily skip this repository."
    )
    protocol: Protocol = Field(
        default=Protocol.HTTPS, description="Override github.protocol for this repo."
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v:
            raise ValueError("Repository URL cannot be empty")

        if not any(re.match(p, v) for p in REPO_URL_PATTERNS):
            raise ValueError(
                f"Invalid repository URL format: {v}. "
                "Supported formats: owner/repo, https://..., git@..."
            )
        return v


class OwnerConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    # DB column and web API use ``owner_type``; the TOML seed key stays
    # ``type`` (accepted via alias) so existing config files keep working.
    owner_type: Literal["user", "organization"] = Field(
        alias="type", description="Owner type."
    )
    name: str = Field(description="GitHub username or organization name.")
    enabled: bool = Field(default=True, description="Set false to skip this owner.")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Owner name cannot be empty")
        return v.strip()


ProposalTrackerKind = Literal["eip", "erc", "pep", "rfc", "dep"]


class ChangelogTrackerConfig(BaseModel):
    name: str = Field(description="Human-readable tracker name.")
    url: HttpUrl = Field(description="Changelog page or file URL.")
    parser_type: Literal["markdown_heading", "html_chinese_version"] = Field(
        description="Version parser type."
    )
    enabled: bool = Field(default=True, description="Set false to skip this tracker.")


class StorageType(str, Enum):
    DB = "db"
    FILE = "file"
    MARKPOST = "markpost"
    AUTO = "auto"


class ReportConfig(BaseModel):
    storage: StorageType = Field(
        default=StorageType.AUTO,
        description="Report storage: 'auto', 'db', 'file', or 'markpost'.",
    )


class WebConfig(BaseModel):
    """Web UI settings.

    ``base_url`` is the public address of the Progress WebUI. It is used to
    build links back to the WebUI inside MarkPost stubs when a report is too
    large to publish in full. It is optional: when unset, oversized reports are
    skipped instead of stubbed.
    """

    base_url: HttpUrl | None = Field(
        default=None,
        description=(
            "Public base URL of the Progress WebUI "
            "(e.g. https://progress.example.com). Used to build links back to the "
            "WebUI inside MarkPost stubs when a report exceeds the size limit. "
            "Optional; when unset, oversized reports are skipped instead of stubbed."
        ),
    )


class OTelConfig(BaseModel):
    """OpenTelemetry infrastructure settings (traces + metrics to files)."""

    enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry traces/metrics export to JSON-Lines files.",
    )
    export_dir: str = Field(
        default="data/telemetry",
        description="Directory for traces.jsonl / metrics.jsonl (infra; relative to cwd).",
    )
    traces: bool = Field(
        default=True,
        description="Export traces (spans) to export_dir/traces.jsonl.",
    )
    metrics: bool = Field(
        default=True,
        description="Export metrics to export_dir/metrics.jsonl.",
    )
    sampling_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Trace sampling ratio; 1.0 captures everything.",
    )


class BugsinkConfig(BaseModel):
    """Bugsink (Sentry-compatible) error-tracking settings."""

    dsn: str | None = Field(
        default=None,
        description="Bugsink DSN, e.g. http://key@host:port/project_id. Empty disables.",
        json_schema_extra={"format": "password", "writeOnly": True},
    )
    environment: str = Field(
        default="production",
        description="Deployment environment tag attached to error events.",
    )


class ObservabilityConfig(BaseModel):
    """Observability infrastructure (OpenTelemetry + Bugsink).

    Treated as infrastructure like data_dir: read from the TOML file /
    environment at startup, never stored in the editable config blob.
    """

    otel: OTelConfig = Field(default_factory=OTelConfig)
    bugsink: BugsinkConfig = Field(default_factory=BugsinkConfig)


class Config(BaseSettings):
    """Application configuration."""

    language: str = Field(
        default="en",
        description="App language for UI text, reports, and notifications.",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone, e.g. 'UTC' or 'Asia/Shanghai'.",
        json_schema_extra={"format": "timezone"},
    )
    data_dir: str = Field(
        default="data",
        description="Base directory for runtime data (infra; not editable here).",
    )
    workspace_dir: str = Field(
        default=WORKSPACE_DIR_DEFAULT,
        description="Directory where repos are cloned (infra).",
    )

    report: ReportConfig = Field(default_factory=ReportConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    observability: ObservabilityConfig = Field(
        default_factory=ObservabilityConfig,
        description="Observability (OpenTelemetry + Bugsink) infrastructure settings.",
    )
    markpost: MarkpostConfig = Field(default_factory=MarkpostConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    github: GitHubConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    repos: List[RepositoryConfig] = Field(
        default_factory=list, description="Repositories to track."
    )
    owners: List[OwnerConfig] = Field(
        default_factory=list, description="GitHub owners to monitor for new repos."
    )
    proposal_trackers: List[ProposalTrackerKind] = Field(
        default_factory=list, description="Proposal kinds to track."
    )
    changelog_trackers: List[ChangelogTrackerConfig] = Field(
        default_factory=list, description="Changelog trackers."
    )

    model_config = SettingsConfigDict(
        env_prefix="PROGRESS_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError(
                f"Invalid timezone configuration: '{v}'. "
                "Please use a valid IANA timezone identifier"
            )
        return v

    @field_validator(
        "repos", "owners", "proposal_trackers", "changelog_trackers", mode="before"
    )
    @classmethod
    def coerce_indexed_dict_to_list(cls, v):
        if v is None:
            return []
        if isinstance(v, dict):
            try:
                items = sorted(v.items(), key=lambda kv: int(kv[0]))
            except Exception:
                return list(v.values())
            return [value for _key, value in items]
        return v

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    @classmethod
    def load_from_file(cls, config_path: str) -> "Config":
        """Load configuration from specified path."""
        path = Path(config_path)
        if not path.exists():
            raise ConfigException(f"Configuration file not found: {config_path}")

        class _Config(cls):
            model_config = SettingsConfigDict(
                toml_file=str(path),
                env_prefix="PROGRESS_",
                env_nested_delimiter="__",
            )

        try:
            return _Config()
        except ValidationError as e:
            error_lines = ["Configuration validation failed:"]
            for error in e.errors():
                loc = " -> ".join(str(item) for item in error["loc"])
                error_lines.append(f"  - {loc}: {error['msg']}")
            raise ConfigException("\n".join(error_lines)) from e

    def get_timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)
