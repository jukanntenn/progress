from __future__ import annotations

from unittest.mock import Mock

import pytest

from progress.notification.base import Channel
from progress.notification.messages.base import Message


def test_message_send_calls_channel() -> None:
    mock_channel = Mock(spec=Channel)

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)
            self._test_payload = "test payload"

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return self._test_payload

    message = TestMessage(mock_channel)
    result = message.send()

    assert result is True
    mock_channel.send.assert_called_once_with("test payload")


def test_message_send_returns_false_on_error() -> None:
    mock_channel = Mock(spec=Channel)
    mock_channel.send.side_effect = Exception("Test error")

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return "test payload"

    message = TestMessage(mock_channel)
    result = message.send(fail_silently=True)

    assert result is False


def test_message_send_raises_on_error_when_not_fail_silently() -> None:
    mock_channel = Mock(spec=Channel)
    mock_channel.send.side_effect = Exception("Test error")

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return "test payload"

    message = TestMessage(mock_channel)

    with pytest.raises(Exception, match="Test error"):
        message.send(fail_silently=False)
