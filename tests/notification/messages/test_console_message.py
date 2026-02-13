from __future__ import annotations

from progress.notification.channels.console import ConsoleChannel
from progress.notification.messages.console import ConsoleMessage


def test_console_message_get_payload_includes_title_and_summary() -> None:
    channel = ConsoleChannel()
    message = ConsoleMessage(
        channel,
        title="Test Title",
        summary="Test summary",
        total_commits=3,
        markpost_url="https://example.com/report",
        repo_statuses={"repo1": "success", "repo2": "failed"},
        batch_index=0,
        total_batches=2,
    )

    payload = message.get_payload()
    assert "Test Title (1/2)" in payload
    assert "Test summary" in payload
    assert "https://example.com/report" in payload
