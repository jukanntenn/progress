from __future__ import annotations

import pytest
from pydantic import ValidationError

from progress.notification.config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
    NotificationChannelConfig,
    NotificationConfig,
)


def test_console_channel_config_defaults() -> None:
    config = ConsoleChannelConfig()
    assert config.type == "console"
    assert config.enabled is True


def test_feishu_channel_config_validation() -> None:
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=10,
    )
    assert config.type == "feishu"
    assert config.enabled is True
    assert config.timeout == 10


def test_feishu_channel_config_requires_url() -> None:
    with pytest.raises(ValidationError):
        FeishuChannelConfig(timeout=10)


def test_email_channel_config_requires_host_and_recipient_when_enabled() -> None:
    with pytest.raises(ValidationError):
        EmailChannelConfig(enabled=True)


def test_notification_channel_discriminator() -> None:
    console = ConsoleChannelConfig()
    feishu = FeishuChannelConfig(webhook_url="https://example.com")
    email = EmailChannelConfig(
        host="smtp.example.com",
        user="user",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )

    channels: list[NotificationChannelConfig] = [console, feishu, email]

    assert isinstance(channels[0], ConsoleChannelConfig)
    assert isinstance(channels[1], FeishuChannelConfig)
    assert isinstance(channels[2], EmailChannelConfig)


def test_notification_config_requires_enabled_channel() -> None:
    config = NotificationConfig(channels=[ConsoleChannelConfig(enabled=False)])
    assert config.channels[0].enabled is False
