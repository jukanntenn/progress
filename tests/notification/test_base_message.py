from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from progress.notification.base import Channel
from progress.notification.messages.base import Message
from typing import override


async def test_message_send_calls_channel() -> None:
    mock_channel = MagicMock(spec=Channel)
    mock_channel.send = AsyncMock(return_value=None)

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)

        @override
        def get_payload(self, context: str) -> str:
            return f"payload:{context}"

    message = TestMessage(mock_channel)
    result = await message.send("test")

    assert result is True
    mock_channel.send.assert_called_once_with("payload:test")


async def test_message_send_returns_false_on_error() -> None:
    mock_channel = MagicMock(spec=Channel)
    mock_channel.send = AsyncMock(side_effect=Exception("Test error"))

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)

        @override
        def get_payload(self, context: str) -> str:
            return "test payload"

    message = TestMessage(mock_channel)
    result = await message.send("test", fail_silently=True)

    assert result is False


async def test_message_send_raises_on_error_when_not_fail_silently() -> None:
    mock_channel = MagicMock(spec=Channel)
    mock_channel.send = AsyncMock(side_effect=Exception("Test error"))

    class TestMessage(Message):
        def __init__(self, channel: Channel) -> None:
            super().__init__(channel)

        @override
        def get_payload(self, context: str) -> str:
            return "test payload"

    message = TestMessage(mock_channel)

    with pytest.raises(Exception, match="Test error"):
        await message.send("test", fail_silently=False)
