"""Notification system: Event → Renderer → Channel (spec 10).

Three fully orthogonal concerns:
- :class:`Event` — pure data ("what happened")
- :class:`Renderer` — pure function (Event + format → payload)
- :class:`Channel` — pure transport (payload + target → result)

The :class:`Dispatcher` orchestrates: for each event, render per-channel
payloads then concurrently ``send`` via ``asyncio.gather``. Failures are
collected into :class:`DispatchOutcome` (never silently swallowed).
"""

from __future__ import annotations

from progress.cli.notifications.base import Channel, ChannelPayload, ContentType, Renderer, SendResult
from progress.cli.notifications.channels import ConsoleChannel, EmailChannel, FeishuChannel
from progress.cli.notifications.config import build_channels
from progress.cli.notifications.dispatcher import DispatchOutcome, Dispatcher
from progress.cli.notifications.events import (
    ChangelogEvent,
    DiscoveredRepoEvent,
    Event,
    NotificationEvent,
    ProposalEvent,
    ReportEvent,
    ReportRepo,
)
from progress.cli.notifications.renderer import JinjaRenderer
from progress.cli.notifications.status import STATUS_SPEC, status_color, status_icon, status_label

__all__ = [
    "STATUS_SPEC",
    "ChangelogEvent",
    "Channel",
    "ChannelPayload",
    "ConsoleChannel",
    "ContentType",
    "DiscoveredRepoEvent",
    "DispatchOutcome",
    "Dispatcher",
    "EmailChannel",
    "Event",
    "FeishuChannel",
    "JinjaRenderer",
    "NotificationEvent",
    "ProposalEvent",
    "Renderer",
    "ReportEvent",
    "ReportRepo",
    "SendResult",
    "build_channels",
    "status_color",
    "status_icon",
    "status_label",
]
