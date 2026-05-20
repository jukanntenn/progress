from __future__ import annotations

from progress.notification.channels.email import EmailChannel
from progress.notification.messages.email import (
    EmailContext,
    EmailMessage,
    EmailProposalContext,
    EmailProposalMessage,
)
from progress.notification.utils import ChangelogEntry, DiscoveredRepo


def _make_email_channel() -> EmailChannel:
    return EmailChannel(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
        starttls=False,
        ssl=False,
    )


def test_email_message_get_payload_includes_subject_and_html() -> None:
    message = EmailMessage(_make_email_channel())
    context = EmailContext(
        title="Test Subject",
        summary="Test summary",
        total_commits=5,
        markpost_url="https://example.com/report",
        repo_statuses={"repo1": "success", "repo2": "failed"},
        batch_index=0,
        total_batches=2,
    )

    payload = message.get_payload(context)
    assert payload.startswith("Subject: Test Subject (1/2)\n\n")
    assert "<html>" in payload
    assert "Test summary" in payload
    assert "https://example.com/report" in payload


def test_email_message_changelog_renders_bullet_list() -> None:
    message = EmailMessage(_make_email_channel())
    entries = [
        ChangelogEntry(
            name="React", version="v19.0.0", url="https://react.dev/changelog"
        ),
        ChangelogEntry(name="Vue", version="v3.5.0", url="https://vuejs.org/changelog"),
    ]
    context = EmailContext(
        title="Changelog Updates",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="changelog",
        changelog_entries=entries,
    )

    payload = message.get_payload(context)
    assert "React" in payload and "v19.0.0" in payload
    assert "Vue" in payload and "v3.5.0" in payload


def test_email_message_discovered_repos_renders_repo_links() -> None:
    message = EmailMessage(_make_email_channel())
    repos = [
        DiscoveredRepo(name="owner1/repo1", url="https://github.com/owner1/repo1"),
        DiscoveredRepo(name="owner2/repo2", url="https://github.com/owner2/repo2"),
    ]
    context = EmailContext(
        title="New Repos Discovered",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="discovered_repos",
        discovered_repos=repos,
    )

    payload = message.get_payload(context)
    assert "owner1/repo1" in payload
    assert "https://github.com/owner1/repo1" in payload
    assert "owner2/repo2" in payload


def test_email_proposal_message_renders_filenames_and_report_link() -> None:
    message = EmailProposalMessage(_make_email_channel())
    context = EmailProposalContext(
        title="Proposal Updates",
        markpost_url="https://example.com/report",
        filenames=["eip-1.md", "eip-2.md"],
        more_count=3,
    )

    payload = message.get_payload(context)
    assert payload.startswith("Subject: Proposal Updates\n\n")
    assert "eip-1.md" in payload
    assert "eip-2.md" in payload
    assert "... and 3 more" in payload
    assert "https://example.com/report" in payload
