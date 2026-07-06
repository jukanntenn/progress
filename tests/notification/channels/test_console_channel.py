from __future__ import annotations

from progress.notification.channels.console import ConsoleChannel


async def test_console_channel_send_prints_payload(capsys) -> None:
    channel = ConsoleChannel()
    payload = "Test notification"
    await channel.send(payload)

    captured = capsys.readouterr()
    assert payload in captured.out
