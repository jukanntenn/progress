"""Notification channel implementations (spec 10)."""

from __future__ import annotations

from progress.cli.notifications.channels.console import ConsoleChannel
from progress.cli.notifications.channels.email import EmailChannel
from progress.cli.notifications.channels.feishu import FeishuChannel

__all__ = [
    "ConsoleChannel",
    "EmailChannel",
    "FeishuChannel",
]
