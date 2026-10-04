"""Notifications hub (PRFC 2026-08-31 phase 3): channel registry + dispatch.

``ctx.notifications`` owns the channel registry and the single dispatch
path; every configured channel kind mounts as its own child fiber and
registers itself, so a third party adds a channel by shipping a plugin —
the extension point the monolithic ``build_channels`` factory never had.
The ``notification/dispatch`` event remains the public observation point;
sending itself flows only through here.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from progress.cli.notifications.base import Channel, Renderer
from progress.cli.notifications.dispatcher import DispatchOutcome, Dispatcher
from progress.cli.notifications.renderer import JinjaRenderer
from progress.kernel import Definition, Entry

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)


class NotificationsService(Definition):
    service_name = "notifications"


class NotificationsHub:
    """Channel registry + the single dispatch path (Renderer stays internal)."""

    def __init__(self, renderer: Renderer) -> None:
        self.renderer = renderer
        self.channels: list[Channel] = []
        self._dispatcher = Dispatcher(self.channels, renderer)

    def register(self, channel: Channel) -> Any:
        self.channels.append(channel)
        self._dispatcher = Dispatcher(list(self.channels), self.renderer)

        async def _remove() -> None:
            if channel in self.channels:
                self.channels.remove(channel)
                self._dispatcher = Dispatcher(list(self.channels), self.renderer)

        return _remove

    async def dispatch(self, event: Any) -> DispatchOutcome:
        if not self.channels:
            logger.debug("no registered notification channels; dispatch is a no-op")
        return await self._dispatcher.dispatch(event)


def make_notifications_entry() -> Entry:
    """The hub plus one child fiber per enabled channel config entry."""

    async def _apply(ctx: Any, config: Any) -> None:
        cfg: CoreConfig = ctx.config
        hub = NotificationsHub(JinjaRenderer(cfg))
        ctx.provide(NotificationsService, hub)
        for index, channel_cfg in enumerate(cfg.notification.channels):
            if not channel_cfg.enabled:
                continue
            ctx.plugin(
                _channel_plugin(channel_cfg.type, channel_cfg),
                name=f"channel-{channel_cfg.type}-{index}",
            )

    return Entry(id="notifications", plugin=_apply, inject=["config", "http"])


def _channel_plugin(kind: str, channel_cfg: Any) -> Any:
    from progress.cli.notifications.channels.console import ConsoleChannel  # noqa: PLC0415
    from progress.cli.notifications.channels.email import EmailChannel  # noqa: PLC0415
    from progress.cli.notifications.channels.feishu import FeishuChannel  # noqa: PLC0415

    async def _apply(ctx: Any, config: Any) -> None:
        if kind == "feishu":
            channel: Channel = FeishuChannel(ctx.http, channel_cfg)
        elif kind == "email":
            channel = EmailChannel(channel_cfg)
        else:
            channel = ConsoleChannel()
        undo = ctx.notifications.register(channel)
        ctx.effect(undo)

    return _apply


__all__ = ["NotificationsHub", "NotificationsService", "make_notifications_entry"]
