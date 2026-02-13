from __future__ import annotations

from progress.notification.config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
)
from progress.notification.factory import create_channel, create_message
from progress.notification.messages import ConsoleMessage, EmailMessage, FeishuMessage


def test_create_channel_returns_console_channel() -> None:
    config = ConsoleChannelConfig(enabled=True)
    channel = create_channel(config)
    assert channel.__class__.__name__ == "ConsoleChannel"


def test_create_channel_returns_feishu_channel() -> None:
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=30,
    )
    channel = create_channel(config)
    assert channel.__class__.__name__ == "FeishuChannel"
    assert channel._webhook_url == "https://example.com/webhook"
    assert channel._timeout == 30


def test_create_channel_returns_email_channel() -> None:
    config = EmailChannelConfig(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )
    channel = create_channel(config)
    assert channel.__class__.__name__ == "EmailChannel"


def test_create_message_returns_console_message() -> None:
    config = ConsoleChannelConfig(enabled=True)
    channel = create_channel(config)
    message = create_message(config, channel, title="T", summary="S", total_commits=1)
    assert isinstance(message, ConsoleMessage)


def test_create_message_returns_feishu_message() -> None:
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=30,
    )
    channel = create_channel(config)
    message = create_message(config, channel, title="T", summary="S", total_commits=1)
    assert isinstance(message, FeishuMessage)


def test_create_message_returns_email_message() -> None:
    config = EmailChannelConfig(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )
    channel = create_channel(config)
    message = create_message(config, channel, title="T", summary="S", total_commits=1)
    assert isinstance(message, EmailMessage)
