from __future__ import annotations

from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from progress.errors import ExternalServiceException
from progress.notification.channels.feishu import FeishuChannel


async def test_feishu_channel_send_success() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"header": {}, "elements": []}'

    with patch("progress.notification.channels.feishu.aiohttp.ClientSession") as mock_session_cls:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()

        session = MagicMock()
        session.post.return_value.__aenter__.return_value = resp
        session.post.return_value.__aexit__.return_value = None

        mock_session_cls.return_value.__aenter__.return_value = session

        await channel.send(payload)

        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        assert kwargs["url"] == "https://example.com/webhook"
        assert kwargs["json"]["msg_type"] == "interactive"
        assert kwargs["json"]["card"] == {"header": {}, "elements": []}
        resp.raise_for_status.assert_called_once()


async def test_feishu_channel_send_raises_on_request_error() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"header": {}, "elements": []}'

    with patch("progress.notification.channels.feishu.aiohttp.ClientSession") as mock_session_cls:
        session = MagicMock()
        session.post.side_effect = aiohttp.ClientError("Connection error")

        mock_session_cls.return_value.__aenter__.return_value = session

        with pytest.raises(
            ExternalServiceException, match="Feishu notification failed"
        ):
            await channel.send(payload)


async def test_feishu_channel_send_raises_on_invalid_json() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = "not-json"

    with pytest.raises(Exception):
        await channel.send(payload)
