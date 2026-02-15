from __future__ import annotations

from progress.notification.channels.console import ConsoleChannel
from progress.notification.messages.console import ConsoleMessage, ConsoleProposalMessage
from progress.notification.utils import ChangelogEntry


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


def test_console_message_changelog_renders_bullet_list() -> None:
    channel = ConsoleChannel()
    entries = [
        ChangelogEntry(name="React", version="v19.0.0", url="https://react.dev/changelog"),
        ChangelogEntry(name="Vue", version="v3.5.0", url="https://vuejs.org/changelog"),
    ]
    message = ConsoleMessage(
        channel,
        title="Changelog Updates",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="changelog",
        changelog_entries=entries,
    )

    payload = message.get_payload()
    assert "• React v19.0.0" in payload
    assert "• Vue v3.5.0" in payload
    assert "https://example.com/report" in payload


def test_console_proposal_message_renders_filenames_and_report_link() -> None:
    channel = ConsoleChannel()
    message = ConsoleProposalMessage(
        channel,
        title="Proposal Updates",
        markpost_url="https://example.com/report",
        filenames=["eip-1.md", "eip-2.md"],
        more_count=3,
    )

    payload = message.get_payload()
    assert "Proposal Updates" in payload
    assert "📄 eip-1.md" in payload
    assert "📄 eip-2.md" in payload
    assert "... and 3 more" in payload
    assert "https://example.com/report" in payload
