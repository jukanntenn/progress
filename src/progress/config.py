"""Configuration file loading and validation."""

import logging
import re
from pathlib import Path
from typing import Annotated, List, Literal, Optional, Union
from zoneinfo import ZoneInfo, available_timezones

from pydantic import (
    BaseModel,
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

from .consts import REPO_URL_PATTERNS
from .enums import Protocol
from .errors import ConfigException

logger = logging.getLogger(__name__)


class FeishuChannelConfig(BaseModel):
    """Feishu webhook notification channel configuration."""

    type: Literal["feishu"] = "feishu"
    enabled: bool = True

    webhook_url: HttpUrl
    timeout: int = Field(default=30, ge=1)


class MarkpostConfig(BaseModel):
    """Markpost configuration."""

    url: HttpUrl
    timeout: int = Field(default=30, ge=1)
    max_batch_size: int = Field(default=1048576, gt=0)


class EmailChannelConfig(BaseModel):
    """Email notification channel configuration."""

    type: Literal["email"] = "email"
    enabled: bool = True

    host: str = ""
    port: int = Field(default=587, ge=1, le=65535)
    user: str = ""
    password: str = ""
    from_addr: str = "progress@example.com"
    recipient: List[str] = Field(default_factory=list)
    starttls: bool = False
    ssl: bool = False

    @model_validator(mode="after")
    def validate_email_config(self) -> "EmailChannelConfig":
        if not self.enabled:
            return self

        missing_fields = []
        if not self.host:
            missing_fields.append("host")
        if not self.recipient:
            missing_fields.append("recipient")

        if missing_fields:
            raise ValueError(
                f"Missing required fields for email notification: {', '.join(missing_fields)}"
            )

        return self


NotificationChannelConfig = Annotated[
    Union[FeishuChannelConfig, EmailChannelConfig],
    Field(discriminator="type"),
]


class NotificationConfig(BaseModel):
    """Notification configuration."""

    channels: List[NotificationChannelConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_notification_config(self) -> "NotificationConfig":
        if not self.channels:
            raise ValueError("At least one notification channel must be configured")
        if not any(getattr(channel, "enabled", True) for channel in self.channels):
            raise ValueError("At least one enabled notification channel is required")
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


class Config(BaseSettings):
    """Application configuration."""

    language: str = Field(default="en")
    timezone: str = Field(default="UTC")

    markpost: MarkpostConfig
    notification: NotificationConfig
    github: GitHubConfig
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    repos: List[RepositoryConfig] = Field(default_factory=list)

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
