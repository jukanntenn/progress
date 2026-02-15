from __future__ import annotations

import json

from progress.notification.channels.feishu import FeishuChannel
from progress.notification.messages.feishu import FeishuMessage, FeishuProposalMessage
from progress.notification.utils import ChangelogEntry, DiscoveredRepo


def test_feishu_message_get_payload_returns_json_card() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    message = FeishuMessage(
        channel,
        title="Test Title",
        summary="Test summary",
        total_commits=10,
        repo_statuses={"repo1": "success", "repo2": "failed", "repo3": "skipped"},
        markpost_url="https://example.com/report",
        batch_index=0,
        total_batches=2,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    assert parsed["msg_type"] == "interactive"
    assert parsed["card"]["header"]["title"]["content"] == "Test Title (1/2)"
    assert isinstance(parsed["card"]["elements"], list)
    assert any(
        e.get("tag") == "action"
        and e.get("actions", [{}])[0].get("url") == "https://example.com/report"
        for e in parsed["card"]["elements"]
    )


def test_feishu_message_changelog_renders_bullet_list() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    entries = [
        ChangelogEntry(name="React", version="v19.0.0", url="https://react.dev/changelog"),
        ChangelogEntry(name="Vue", version="v3.5.0", url="https://vuejs.org/changelog"),
    ]
    message = FeishuMessage(
        channel,
        title="Changelog Updates",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="changelog",
        changelog_entries=entries,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    assert parsed["card"]["card_link"]["url"] == "https://example.com/report"
    elements = parsed["card"]["elements"]
    content_elements = [e for e in elements if e.get("tag") == "div"]
    assert any("React v19.0.0" in e["text"]["content"] for e in content_elements)
    assert any("Vue v3.5.0" in e["text"]["content"] for e in content_elements)


def test_feishu_message_discovered_repos_renders_repo_links() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    repos = [
        DiscoveredRepo(name="owner1/repo1", url="https://github.com/owner1/repo1"),
        DiscoveredRepo(name="owner2/repo2", url="https://github.com/owner2/repo2"),
    ]
    message = FeishuMessage(
        channel,
        title="New Repos Discovered",
        summary="",
        total_commits=0,
        markpost_url="https://example.com/report",
        notification_type="discovered_repos",
        discovered_repos=repos,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    assert parsed["card"]["card_link"]["url"] == "https://example.com/report"
    elements = parsed["card"]["elements"]
    content_elements = [e for e in elements if e.get("tag") == "div"]
    assert any(
        "[owner1/repo1](https://github.com/owner1/repo1)" in e["text"]["content"]
        for e in content_elements
    )
    assert any(
        "[owner2/repo2](https://github.com/owner2/repo2)" in e["text"]["content"]
        for e in content_elements
    )


def test_feishu_message_discovered_repos_truncates_at_5() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    repos = [
        DiscoveredRepo(
            name=f"owner/repo{i}", url=f"https://github.com/owner/repo{i}"
        )
        for i in range(8)
    ]
    message = FeishuMessage(
        channel,
        title="New Repos",
        summary="",
        total_commits=0,
        notification_type="discovered_repos",
        discovered_repos=repos,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    elements = parsed["card"]["elements"]
    content_elements = [e for e in elements if e.get("tag") == "div"]
    repo_links = [e for e in content_elements if "github.com" in e["text"]["content"]]
    assert len(repo_links) == 5
    assert any("... and 3 more" in e["text"]["content"] for e in content_elements)


def test_feishu_proposal_message_renders_filenames_and_card_link() -> None:
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    message = FeishuProposalMessage(
        channel,
        title="Proposal Updates",
        markpost_url="https://example.com/report",
        filenames=["eip-1.md", "eip-2.md"],
        more_count=3,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    assert parsed["msg_type"] == "interactive"
    assert parsed["card"]["card_link"]["url"] == "https://example.com/report"
    elements = parsed["card"]["elements"]
    content_elements = [e for e in elements if e.get("tag") == "div"]
    assert any("eip-1.md" in e["text"]["content"] for e in content_elements)
    assert any("eip-2.md" in e["text"]["content"] for e in content_elements)
    assert any("... and 3 more" in e["text"]["content"] for e in content_elements)
