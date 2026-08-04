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
    enabled: bool = True
    host: str = ""
    port: int = 465
    user: str = ""
    password: SecretStr = SecretStr("")
    from_addr: str = ""
    recipient: list[str] = Field(default_factory=list)
    starttls: bool = False
    ssl: bool = True


class ConsoleChannelConfig(BaseModel):
    """Console (structlog) channel."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["console"] = "console"
    enabled: bool = True


class FeishuChannelConfig(BaseModel):
    """Feishu webhook channel."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["feishu"] = "feishu"
    enabled: bool = True
    webhook_url: SecretStr = SecretStr("")


ChannelConfig = Annotated[
    EmailChannelConfig | ConsoleChannelConfig | FeishuChannelConfig,
    Field(discriminator="type"),
]


class NotificationConfig(BaseModel):
    """Notification channels (classic TOML discriminated union)."""

    model_config = ConfigDict(extra="forbid")
    channels: list[ChannelConfig] = Field(default_factory=lambda: [ConsoleChannelConfig()])  # ty: ignore[invalid-assignment]


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
