"""Notification channel protocol and shared types (spec 10).

Per spec 10, the notification system has three fully orthogonal concerns:

- **Event** (pure data) — what happened (repo report, proposal event, etc.)
- **Renderer** (pure function) — render an event into a channel-format payload
- **Channel** (pure transport) — deliver a rendered payload to a target

Channels know nothing about events; events know nothing about channels. The
Renderer bridges them. This replaces the legacy N×M class matrix
(ConsoleMessage × EmailMessage × FeishuMessage × proposal variants) with a
declarative template matrix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ContentType(StrEnum):
    """Payload content format — determines which channel can accept it."""

    HTML = "html"
    PLAIN_TEXT = "plain_text"
    CARD_JSON = "card_json"


@dataclass
class ChannelPayload:
    """Channel-agnostic rendered payload.

    - ``title``: email subject / Feishu header / console headline
    - ``body``: already-rendered target-format body
    - ``content_type``: HTML / PLAIN_TEXT / CARD_JSON
    - ``metadata``: channel-specific delivery params (recipients, at-users, …)
    """

    title: str
    body: str
    content_type: ContentType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SendResult:
    """Outcome of one channel send."""

    channel: str
    ok: bool
    error: str | None = None


@runtime_checkable
class Channel(Protocol):
    """Pure transport: deliver ``payload`` to a target.

    Knows nothing about event types. Does not render content.
    """

    name: str

    async def send(self, payload: ChannelPayload) -> SendResult: ...


@runtime_checkable
class Renderer(Protocol):
    """Pure function bridge: render ``event`` into a channel-format payload.

    No IO, no async. Easy to unit-test.
    """

    def render(self, event: Any, content_type: ContentType) -> ChannelPayload: ...


__all__ = ["Channel", "ChannelPayload", "ContentType", "Renderer", "SendResult"]
