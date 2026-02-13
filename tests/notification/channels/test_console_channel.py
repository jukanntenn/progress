from __future__ import annotations

from progress.notification.channels.console import ConsoleChannel


def test_console_channel_send_prints_payload(capsys) -> None:
    channel = ConsoleChannel()
    payload = "Test notification"
    channel.send(payload)

    captured = capsys.readouterr()
    assert payload in captured.out
