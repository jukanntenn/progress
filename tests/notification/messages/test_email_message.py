from __future__ import annotations

from progress.notification.channels.email import EmailChannel
from progress.notification.messages.email import EmailMessage, EmailProposalMessage
from progress.notification.utils import ChangelogEntry


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


def test_email_message_changelog_renders_bullet_list() -> None:
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
    entries = [
        ChangelogEntry(name="React", version="v19.0.0", url="https://react.dev/changelog"),
        ChangelogEntry(name="Vue", version="v3.5.0", url="https://vuejs.org/changelog"),
    ]
    message = EmailMessage(
        channel,
        title="Changelog Updates",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="changelog",
        changelog_entries=entries,
    )

    payload = message.get_payload()
    assert "React" in payload and "v19.0.0" in payload
    assert "Vue" in payload and "v3.5.0" in payload


def test_email_proposal_message_renders_filenames_and_report_link() -> None:
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
    message = EmailProposalMessage(
        channel,
        title="Proposal Updates",
        markpost_url="https://example.com/report",
        filenames=["eip-1.md", "eip-2.md"],
        more_count=3,
    )

    payload = message.get_payload()
    assert payload.startswith("Subject: Proposal Updates\n\n")
    assert "eip-1.md" in payload
    assert "eip-2.md" in payload
    assert "... and 3 more" in payload
    assert "https://example.com/report" in payload
