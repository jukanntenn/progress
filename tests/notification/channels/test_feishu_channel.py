from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from progress.errors import ExternalServiceException
from progress.notification.channels.feishu import FeishuChannel


def test_feishu_channel_send_success() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"msg_type": "interactive", "card": {"header": {}, "elements": []}}'

    with patch("requests.post") as mock_post:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        channel.send(payload)

        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        assert kwargs["url"] == "https://example.com/webhook"
        assert kwargs["timeout"] == 30
        assert kwargs["json"]["msg_type"] == "interactive"
        mock_response.raise_for_status.assert_called_once()


def test_feishu_channel_send_raises_on_request_error() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"text": "test"}'

    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("Connection error")

        with pytest.raises(
            ExternalServiceException, match="Feishu notification failed"
        ):
            channel.send(payload)


def test_feishu_channel_send_raises_on_invalid_json() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = "not-json"

    with pytest.raises(ExternalServiceException, match="Feishu notification failed"):
        channel.send(payload)
