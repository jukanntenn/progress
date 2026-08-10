"""Notification channel configuration models + factory (spec 02, 10).

Per spec 02, domain config models live in their respective packages.
NotificationConfig is the classic TOML discriminated union for notification
channels, owned by ``cli/notifications/``.
"""

from __future__ import annotations

from typing import Annotated, Literal

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from progress.cli.notifications.base import Channel
from progress.cli.notifications.channels.console import ConsoleChannel
from progress.cli.notifications.channels.email import EmailChannel
from progress.cli.notifications.channels.feishu import FeishuChannel


class EmailChannelConfig(BaseModel):
    """SMTP email channel (classic discriminated union member)."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["email"] = "email"
    enabled: bool = Field(
        default=True,
        title="Enable This Channel",
        description="When enabled, this channel receives notifications.",
    )
    host: str = Field(
        default="",
        title="SMTP Host",
        description="SMTP server hostname.",
        examples=["smtp.gmail.com"],
    )
    port: int = Field(
        default=465,
        title="SMTP Port",
        description="SMTP server port. 465 for SSL, 587 for STARTTLS.",
        examples=[465, 587],
    )
    user: str = Field(
        default="",
        title="SMTP Username",
        description="Username for SMTP authentication.",
        examples=["postmaster@example.com"],
    )
    password: SecretStr = Field(
        default=SecretStr(""),
        title="SMTP Password",
        description="Password for SMTP authentication.",
    )
    from_addr: str = Field(
        default="",
        title="From Address",
        description="Email address appearing in the From header.",
        examples=["progress@example.com"],
    )
    recipient: list[str] = Field(
        default_factory=list,
        title="Recipients",
        description="Email addresses that receive notifications. Press Enter or comma to add each address.",
        examples=["alice@example.com", "bob@example.com"],
        json_schema_extra={"format": "email"},
    )
    starttls: bool = Field(
        default=False,
        title="Use STARTTLS",
        description="Upgrade the connection to TLS after connecting. Typically used with port 587.",
    )
    ssl: bool = Field(
        default=True,
        title="Use SSL",
        description="Connect over implicit TLS. Typically used with port 465.",
    )


class ConsoleChannelConfig(BaseModel):
    """Console (structlog) channel."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["console"] = "console"
    enabled: bool = Field(
        default=True,
        title="Enable This Channel",
        description="When enabled, notifications are written to the application log (console).",
    )


class FeishuChannelConfig(BaseModel):
    """Feishu webhook channel."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["feishu"] = "feishu"
    enabled: bool = Field(
        default=True,
        title="Enable This Channel",
        description="When enabled, this channel receives notifications.",
    )
    webhook_url: SecretStr = Field(
        default=SecretStr(""),
        title="Webhook URL",
        description="Feishu custom bot webhook URL.",
    )


ChannelConfig = Annotated[
    EmailChannelConfig | ConsoleChannelConfig | FeishuChannelConfig,
    Field(discriminator="type"),
]


class NotificationConfig(BaseModel):
    """Notification channels (classic TOML discriminated union)."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "notifications", "ui_order": 10},
    )
    channels: list[ChannelConfig] = Field(  # ty: ignore[invalid-assignment]
        default_factory=lambda: [ConsoleChannelConfig()],
        title="Notification Channels",
        description="Channels that receive notifications when reports are generated. Add one per delivery method.",
    )


def build_channels(
    config: NotificationConfig,
    *,
    session: aiohttp.ClientSession | None = None,
) -> list[Channel]:
    """Instantiate enabled channels from ``config``.

    ``session`` is required if any Feishu channel is enabled (webhook POST).
    Email uses aiosmtplib's own connection, so it doesn't need a session.
    """
    channels: list[Channel] = []
    for channel_cfg in config.channels:
        if not channel_cfg.enabled:
            continue
        if channel_cfg.type == "console":
            channels.append(ConsoleChannel())
        elif channel_cfg.type == "email":
            channels.append(EmailChannel(channel_cfg))
        elif channel_cfg.type == "feishu":
            if session is None:
                raise ValueError("aiohttp session is required for the feishu channel")
            channels.append(FeishuChannel(session, channel_cfg))
    return channels


__all__ = [
    "ChannelConfig",
    "ConsoleChannelConfig",
    "EmailChannelConfig",
    "FeishuChannelConfig",
    "NotificationConfig",
    "build_channels",
]
