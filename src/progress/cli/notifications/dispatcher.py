"""Notification dispatcher (spec 10).

The dispatcher orchestrates: for each event, look up which channels should
receive it, render a per-channel payload, then concurrently ``send`` via
``asyncio.gather``. Failures are collected into ``DispatchOutcome`` rather
than silently swallowed (per spec 10's mandate to fix the legacy
``fail_silently=True`` default).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging

from progress.cli.notifications.base import Channel, ChannelPayload, ContentType, Renderer, SendResult
from progress.cli.notifications.events import Event

logger = logging.getLogger(__name__)


@dataclass
class DispatchOutcome:
    """Aggregated result of dispatching one event to all channels."""

    results: list[SendResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results) if self.results else True

    @property
    def errors(self) -> list[str]:
        return [r.error for r in self.results if not r.ok and r.error]


class Dispatcher:
    """Orchestrate event → render → channel send."""

    def __init__(self, channels: list[Channel], renderer: Renderer) -> None:
        self._channels = channels
        self._renderer = renderer

    async def dispatch(self, event: Event) -> DispatchOutcome:
        if not self._channels:
            return DispatchOutcome()
        payloads: list[tuple[Channel, ChannelPayload]] = []
        for channel in self._channels:
            content_type = _channel_content_type(channel.name)
            payload = self._renderer.render(event, content_type)
            payloads.append((channel, payload))
        results = await asyncio.gather(*[ch.send(p) for ch, p in payloads], return_exceptions=True)
        outcome = DispatchOutcome()
        for channel, result in zip(payloads, results, strict=False):
            if isinstance(result, Exception):
                channel_name = channel[0].name
                logger.warning(
                    "notification send failed: event=%s channel=%s error=%s",
                    getattr(event, "kind", "unknown"),
                    channel_name,
                    result,
                )
                outcome.results.append(SendResult(channel=channel_name, ok=False, error=str(result)))
            else:
                assert isinstance(result, SendResult)
                logger.info(
                    "notification sent: event=%s channel=%s",
                    getattr(event, "kind", "unknown"),
                    channel[0].name,
                )
                outcome.results.append(result)
        return outcome


def _channel_content_type(name: str) -> ContentType:
    """Map a channel name to the content type its renderer should produce."""
    if name == "email":
        return ContentType.HTML
    if name == "feishu":
        return ContentType.CARD_JSON
    return ContentType.PLAIN_TEXT


__all__ = ["DispatchOutcome", "Dispatcher"]
