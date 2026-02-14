"""Configuration file loading and validation."""

import logging
import re
from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, available_timezones

from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator
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

    enabled: bool = False
    url: HttpUrl | None = None
    timeout: int = Field(default=30, ge=1)
    max_batch_size: int = Field(default=1048576, gt=0)

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

    gh_token: str
    protocol: Protocol = Field(default=Protocol.HTTPS)
    proxy: str = ""
    git_timeout: int = Field(default=300, ge=1)
    gh_timeout: int = Field(default=300, ge=1)


class AnalysisConfig(BaseModel):
    """Claude Code analysis configuration."""

    max_diff_length: int = Field(default=100000, gt=0)
    concurrency: int = Field(default=1, ge=1)
    timeout: int = Field(default=600, ge=1)
    language: str = Field(default="en")
    first_run_lookback_commits: int = Field(default=3, ge=1)


class WebConfig(BaseModel):
    """Web service configuration."""

    enabled: bool = False
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=5000, ge=1, le=65535)
    debug: bool = Field(default=False)
    reload: bool = Field(default=True)


class RepositoryConfig(BaseModel):
    """Repository configuration."""

    url: str
    branch: str = "main"
    enabled: bool = True
    protocol: Protocol = Field(default=Protocol.HTTPS)

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
    type: Literal["user", "organization"]
    name: str
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Owner name cannot be empty")
        return v.strip()


class ProposalTrackerConfig(BaseModel):
    type: Literal["eip", "rust_rfc", "pep", "django_dep"]
    repo_url: str
    branch: str = "main"
    enabled: bool = True
    proposal_dir: str = ""
    file_pattern: str = ""

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("repo_url cannot be empty")

        v = v.strip()
        if not re.match(r"^https://github\.com/[^/]+/[^/]+(\.git)?$", v):
            raise ValueError(
                f"Invalid GitHub repo_url format: {v}. Expected https://github.com/<owner>/<repo>(.git)"
            )
        return v


class ChangelogTrackerConfig(BaseModel):
    name: str
    url: HttpUrl
    parser_type: Literal["markdown_heading", "html_chinese_version"]
    enabled: bool = True


class StorageType(str, Enum):
    DB = "db"
    FILE = "file"
    MARKPOST = "markpost"
    AUTO = "auto"


class ReportConfig(BaseModel):
    storage: StorageType = StorageType.AUTO


class Config(BaseSettings):
    """Application configuration."""

    language: str = Field(default="en")
    timezone: str = Field(default="UTC")
    data_dir: str = Field(default="data")
    workspace_dir: str = Field(default=WORKSPACE_DIR_DEFAULT)

    report: ReportConfig = Field(default_factory=ReportConfig)
    markpost: MarkpostConfig = Field(default_factory=MarkpostConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    github: GitHubConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    repos: List[RepositoryConfig] = Field(default_factory=list)
    owners: List[OwnerConfig] = Field(default_factory=list)
    proposal_trackers: List[ProposalTrackerConfig] = Field(default_factory=list)
    changelog_trackers: List[ChangelogTrackerConfig] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_prefix="PROGRESS_",
        env_nested_delimiter="__",
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

    @field_validator("repos", "owners", "proposal_trackers", "changelog_trackers", mode="before")
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
