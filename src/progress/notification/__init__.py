from __future__ import annotations

from .base import Channel
from .config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
    NotificationChannelConfig,
    NotificationConfig,
)
from .factory import create_channel, create_message, create_proposal_message
from .utils import ChangelogEntry, NotificationType

__all__ = [
    "Channel",
    "ChangelogEntry",
    "ConsoleChannelConfig",
    "EmailChannelConfig",
    "FeishuChannelConfig",
    "NotificationChannelConfig",
    "NotificationConfig",
    "NotificationType",
    "create_channel",
    "create_message",
    "create_proposal_message",
]
