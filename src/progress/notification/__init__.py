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
from .messages import (
    ConsoleContext,
    ConsoleProposalContext,
    EmailContext,
    EmailProposalContext,
    FeishuContext,
    FeishuProposalContext,
)
from .utils import ChangelogEntry, DiscoveredRepo, NotificationType

__all__ = [
    "Channel",
    "ChangelogEntry",
    "ConsoleChannelConfig",
    "ConsoleContext",
    "ConsoleProposalContext",
    "DiscoveredRepo",
    "EmailChannelConfig",
    "EmailContext",
    "EmailProposalContext",
    "FeishuChannelConfig",
    "FeishuContext",
    "FeishuProposalContext",
    "NotificationChannelConfig",
    "NotificationConfig",
    "NotificationType",
    "create_channel",
    "create_message",
    "create_proposal_message",
]
