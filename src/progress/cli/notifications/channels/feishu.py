"""Feishu webhook channel (spec 10).

The ``card_json.j2`` template for each event kind renders the **complete**
Feishu interactive card as a JSON document (header + elements array, with real
``hr`` / ``fields`` / ``action`` / ``card_link`` elements). This channel only
parses that JSON once (``json.loads``) and POSTs it to the webhook — no
Pydantic card model and no string-to-single-div flattening in between. The
template is the single source of truth for the card's structure.

Per spec 10, ``send`` does NOT swallow exceptions — the Dispatcher collects
failures into ``DispatchOutcome``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from progress.cli.notifications.base import ChannelPayload, SendResult
from progress.errors import NotificationException

if TYPE_CHECKING:
    import aiohttp

    from progress.cli.notifications.config import FeishuChannelConfig


class FeishuChannel:
    """Send a Feishu interactive card via webhook.

    ``payload.body`` is the JSON document produced by the ``card_json.j2``
    template (a Feishu card object). ``payload.title`` is the channel-rendered
    title (with batch indicator already applied); the template is expected to
    embed it in the card header.
    """

    name = "feishu"

    def __init__(self, session: aiohttp.ClientSession, config: FeishuChannelConfig) -> None:
        self._session = session
        self._config = config

    async def send(self, payload: ChannelPayload) -> SendResult:
        webhook_url = self._config.webhook_url.get_secret_value() if self._config.webhook_url else ""
        _validate_webhook_url(webhook_url)
        try:
            card = json.loads(payload.body)
        except (json.JSONDecodeError, TypeError) as e:
            raise NotificationException(f"feishu card_json template did not produce valid JSON: {e}") from e
        body = {"msg_type": "interactive", "card": card}
        async with self._session.post(webhook_url, json=body) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise NotificationException(f"feishu webhook returned {resp.status}: {text[:200]}")
            data = await resp.json()
        if data.get("code", 0) != 0:
            raise NotificationException(f"feishu API error: {data.get('msg', 'unknown')}")
        return SendResult(channel=self.name, ok=True)


def _validate_webhook_url(webhook_url: str) -> None:
    """Raise a readable error when the webhook URL is missing or masked.

    A SecretStr field that round-tripped the mask sentinel (``**********``)
    used to reach ``aiohttp.post`` as the URL, producing an opaque
    ``InvalidUrlClientError`` whose message was just ``**********`` — making
    the failure impossible to diagnose. Validating up front yields a clear,
    loggable error instead.
    """
    if not webhook_url:
        raise NotificationException("feishu webhook_url is not configured")
    parsed = urlparse(webhook_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise NotificationException("feishu webhook_url is invalid or appears masked; expected an https URL")


__all__ = ["FeishuChannel"]
