from __future__ import annotations

import json

from progress.notification.channels.feishu import FeishuChannel
from progress.notification.messages.feishu import FeishuMessage


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
