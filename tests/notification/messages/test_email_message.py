from __future__ import annotations

from progress.notification.channels.email import EmailChannel
from progress.notification.messages.email import EmailMessage


def test_email_message_get_payload_includes_subject_and_html() -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
        starttls=False,
        ssl=False,
    )
    message = EmailMessage(
        channel,
        title="Test Subject",
        summary="Test summary",
        total_commits=5,
        markpost_url="https://example.com/report",
        repo_statuses={"repo1": "success", "repo2": "failed"},
        batch_index=0,
        total_batches=2,
    )

    payload = message.get_payload()
    assert payload.startswith("Subject: Test Subject (1/2)\n\n")
    assert "<html>" in payload
    assert "Test summary" in payload
    assert "https://example.com/report" in payload
