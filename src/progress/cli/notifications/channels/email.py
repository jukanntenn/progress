"""Email channel: sends HTML payload via aiosmtplib (spec 10).

Per spec 10, the legacy email channel had two bugs:
- ``server.close()`` followed by ``quit()`` (should be one or the other)
- ``connect()`` failure still called ``quit()``

This implementation uses aiosmtplib's module-level :func:`aiosmtplib.send`,
which owns its own connection lifecycle (no manual connect/quit/close).
Per spec 10, ``send`` does NOT swallow exceptions — the Dispatcher collects
failures into ``DispatchOutcome``.
"""

from __future__ import annotations

from email.message import EmailMessage
import logging
from typing import TYPE_CHECKING

import aiosmtplib

from progress.cli.notifications.base import ChannelPayload, ContentType, SendResult
from progress.errors import NotificationException

if TYPE_CHECKING:
    from progress.cli.notifications.config import EmailChannelConfig

logger = logging.getLogger(__name__)

SMTP_TIMEOUT: float = 10.0


class EmailChannel:
    """Send HTML email via SMTP."""

    name = "email"

    def __init__(self, config: EmailChannelConfig) -> None:
        self._config = config

    async def send(self, payload: ChannelPayload) -> SendResult:
        cfg = self._config
        if not cfg.recipient:
            raise NotificationException("email channel has no recipients configured")
        if payload.content_type != ContentType.HTML:
            logger.warning(
                "email channel received %s payload; expected HTML",
                payload.content_type.value,
            )
        msg = EmailMessage()
        msg["Subject"] = payload.title
        msg["From"] = cfg.from_addr
        msg["To"] = ", ".join(cfg.recipient)
        msg.set_content(payload.body, subtype="html")
        password = cfg.password.get_secret_value() if cfg.password else ""
        await aiosmtplib.send(
            msg,
            hostname=cfg.host,
            port=cfg.port,
            username=cfg.user or None,
            password=password or None,
            start_tls=cfg.starttls,
            use_tls=cfg.ssl,
            timeout=SMTP_TIMEOUT,
        )
        return SendResult(channel=self.name, ok=True)


__all__ = ["EmailChannel"]
