"""Unit tests for ``progress.cli.notifications`` (spec 10).

Tests the three orthogonal concerns (Event / Renderer / Channel) without IO:
- ContentType / ChannelPayload / SendResult data shape
- Dispatcher collect + concurrent send + outcome aggregation
- JinjaRenderer template lookup + fallback
- Channel implementations (ConsoleChannel, EmailChannel, FeishuChannel)
"""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from rich.console import Console as RichConsole

from progress.cli.notifications.base import (
    Channel,
    ChannelPayload,
    ContentType,
    Renderer,
    SendResult,
)
from progress.cli.notifications.channels.console import ConsoleChannel
from progress.cli.notifications.channels.feishu import FeishuChannel
from progress.cli.notifications.config import FeishuChannelConfig
from progress.cli.notifications.dispatcher import (
    DispatchOutcome,
    Dispatcher,
    _channel_content_type,
)
from progress.cli.notifications.events import (
    NotificationEvent,
    ReportEvent,
)
from progress.cli.notifications.renderer import JinjaRenderer
from progress.errors import NotificationException


class TestContentType:
    def test_is_str_enum(self) -> None:
        assert ContentType.HTML == "html"
        assert ContentType.PLAIN_TEXT == "plain_text"
        assert ContentType.CARD_JSON == "card_json"

    def test_values(self) -> None:
        assert {c.value for c in ContentType} == {"html", "plain_text", "card_json"}


class TestChannelPayload:
    def test_default_metadata(self) -> None:
        p = ChannelPayload(title="t", body="b", content_type=ContentType.HTML)
        assert p.metadata == {}

    def test_metadata_field(self) -> None:
        p = ChannelPayload(
            title="t",
            body="b",
            content_type=ContentType.HTML,
            metadata={"recipients": ["a@b"]},
        )
        assert p.metadata["recipients"] == ["a@b"]


class TestSendResult:
    def test_basic_ok(self) -> None:
        r = SendResult(channel="console", ok=True)
        assert r.channel == "console"
        assert r.ok is True
        assert r.error is None

    def test_error(self) -> None:
        r = SendResult(channel="email", ok=False, error="boom")
        assert r.ok is False
        assert r.error == "boom"


class TestProtocols:
    def test_console_channel_is_channel(self) -> None:
        ch = ConsoleChannel()
        assert isinstance(ch, Channel)

    def test_jinja_renderer_is_renderer(self) -> None:
        r = JinjaRenderer()
        assert isinstance(r, Renderer)


class TestDispatcher:
    async def test_dispatch_no_channels_returns_empty(self) -> None:
        d = Dispatcher(channels=[], renderer=JinjaRenderer())
        outcome = await d.dispatch(ReportEvent(title="t", summary="s"))
        assert outcome.results == []
        assert outcome.ok is True

    async def test_dispatch_collects_results(self) -> None:
        ch1 = MagicMock(spec=Channel)
        ch1.name = "console"
        ch1.send = AsyncMock(return_value=SendResult(channel="console", ok=True))
        ch2 = MagicMock(spec=Channel)
        ch2.name = "email"
        ch2.send = AsyncMock(return_value=SendResult(channel="email", ok=True))

        d = Dispatcher(channels=[ch1, ch2], renderer=JinjaRenderer())
        outcome = await d.dispatch(ReportEvent(title="t", summary="s"))
        assert len(outcome.results) == 2
        assert outcome.ok is True

    async def test_dispatch_collects_failure(self) -> None:
        ch = MagicMock(spec=Channel)
        ch.name = "email"
        ch.send = AsyncMock(return_value=SendResult(channel="email", ok=False, error="boom"))
        d = Dispatcher(channels=[ch], renderer=JinjaRenderer())
        outcome = await d.dispatch(ReportEvent(title="t", summary="s"))
        assert outcome.ok is False
        assert outcome.errors == ["boom"]

    async def test_dispatch_gather_exception_wrapped(self) -> None:
        ch = MagicMock(spec=Channel)
        ch.name = "email"
        ch.send = AsyncMock(side_effect=RuntimeError("network died"))
        d = Dispatcher(channels=[ch], renderer=JinjaRenderer())
        outcome = await d.dispatch(ReportEvent(title="t", summary="s"))
        assert outcome.ok is False
        assert "network died" in outcome.errors[0]


class TestChannelContentType:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("email", ContentType.HTML),
            ("feishu", ContentType.CARD_JSON),
            ("console", ContentType.PLAIN_TEXT),
            ("unknown", ContentType.PLAIN_TEXT),
        ],
    )
    def test_mapping(self, name: str, expected: ContentType) -> None:
        assert _channel_content_type(name) == expected


class TestJinjaRenderer:
    def test_render_notification_html(self) -> None:
        r = JinjaRenderer()
        event = NotificationEvent(kind="repo_update", title="t", summary="s")
        payload = r.render(event, ContentType.HTML)
        assert payload.title == "t"
        assert payload.content_type == ContentType.HTML

    def test_render_notification_includes_markpost_url_metadata(self) -> None:
        r = JinjaRenderer()
        event = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="https://markpost.example/r/1",
        )
        payload = r.render(event, ContentType.HTML)
        assert payload.metadata["report_url"] == "https://markpost.example/r/1"

    def test_notification_title_appends_batch_indicator(self) -> None:
        r = JinjaRenderer()
        event = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            batch_index=1,
            total_batches=3,
        )
        payload = r.render(event, ContentType.PLAIN_TEXT)
        assert payload.title == "t (2/3)"

    def test_notification_title_no_indicator_single_batch(self) -> None:
        r = JinjaRenderer()
        event = NotificationEvent(kind="proposal", title="Proposal updates")
        payload = r.render(event, ContentType.PLAIN_TEXT)
        assert payload.title == "Proposal updates"

    def test_render_report_event_still_supported(self) -> None:
        r = JinjaRenderer()
        event = ReportEvent(title="t", summary="s", report_url="https://example.com/r/1")
        payload = r.render(event, ContentType.HTML)
        assert payload.title == "t"
        assert payload.metadata["report_url"] == "https://example.com/r/1"

    def test_render_repo_update_card_json_is_valid_card(self) -> None:

        r = JinjaRenderer()
        event = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="https://markpost.example/r/1",
            data={"repo_statuses": {"a": "success"}, "total_commits": 1, "total_repos": 1},
        )
        payload = r.render(event, ContentType.CARD_JSON)
        assert payload.title == "t"
        card = json.loads(payload.body)
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "t"
        assert card["card_link"] == {"url": "https://markpost.example/r/1"}
        # v2: elements live under body.elements; first is the overview markdown
        assert card["body"]["elements"][0]["tag"] == "markdown"

    def test_render_changelog_card_json_is_valid(self) -> None:

        r = JinjaRenderer()
        event = NotificationEvent(
            kind="changelog",
            title="t",
            markpost_url="https://markpost.example/c",
            data={"entries": [{"name": "uTools", "version": "7.8.0", "url": "https://u.tools", "level": "MINOR"}]},
        )
        card = json.loads(r.render(event, ContentType.CARD_JSON).body)
        # version appears in the first entry's column markdown
        first_entry = card["body"]["elements"][1]  # [0]=heading, [1]=first column_set
        entry_md = first_entry["columns"][0]["elements"][0]["content"]
        assert "uTools" in entry_md
        assert "7.8.0" in entry_md


class TestConsoleChannel:
    async def test_send_ok(self) -> None:
        ch = ConsoleChannel()
        payload = ChannelPayload(title="t", body="b", content_type=ContentType.PLAIN_TEXT)
        result = await ch.send(payload)
        assert result.ok is True
        assert result.channel == "console"
        assert result.error is None

    async def test_send_prints_rich_card_for_known_kind(self) -> None:
        ch = ConsoleChannel()
        ch._console = RichConsole(file=io.StringIO(), force_terminal=False, width=80, record=True)
        event = NotificationEvent(
            kind="repo_update",
            title="Progress Report",
            summary="2 repos updated",
            markpost_url="https://markpost.example/r/1",
            data={
                "repo_statuses": {"good/repo": "success", "bad/repo": "failed"},
                "repo_urls": {"good/repo": "https://github.com/good/repo", "bad/repo": "https://github.com/bad/repo"},
                "total_commits": 5,
            },
        )
        payload = JinjaRenderer().render(event, ContentType.PLAIN_TEXT)
        await ch.send(payload)
        output = ch._console.export_text()
        # the rich card frame (panel border + title + status badge) is on stdout
        assert "Progress Report" in output
        assert "FAILED" in output
        assert "bad/repo" in output
        assert "View Detailed Report" in output

    async def test_send_falls_back_to_body_for_unknown_kind(self) -> None:
        ch = ConsoleChannel()
        ch._console = RichConsole(file=io.StringIO(), force_terminal=False, width=80, record=True)
        # no event in metadata → no structured card → plain body printed
        payload = ChannelPayload(title="t", body="plain fallback body", content_type=ContentType.PLAIN_TEXT)
        await ch.send(payload)
        output = ch._console.export_text()
        assert "plain fallback body" in output


class TestDispatchOutcome:
    def test_ok_with_no_results(self) -> None:
        o = DispatchOutcome()
        assert o.ok is True
        assert o.errors == []

    def test_ok_with_all_ok(self) -> None:
        o = DispatchOutcome(results=[SendResult(channel="a", ok=True), SendResult(channel="b", ok=True)])
        assert o.ok is True

    def test_not_ok_with_failure(self) -> None:
        o = DispatchOutcome(results=[SendResult(channel="a", ok=False, error="x")])
        assert o.ok is False
        assert o.errors == ["x"]


class TestFeishuWebhookValidation:
    """A masked/invalid webhook_url must produce a readable error, not the
    opaque ``**********`` that ``aiohttp.InvalidUrlClientError`` would yield."""

    @staticmethod
    def _channel(webhook_url: str) -> FeishuChannel:
        return FeishuChannel(session=MagicMock(), config=FeishuChannelConfig(webhook_url=webhook_url))

    async def test_empty_url_raises_readable_error(self) -> None:
        ch = self._channel("")
        with pytest.raises(NotificationException, match="not configured"):
            await ch.send(ChannelPayload(title="t", body="{}", content_type=ContentType.CARD_JSON))

    async def test_masked_url_raises_readable_error(self) -> None:
        ch = self._channel("**********")
        with pytest.raises(NotificationException, match="invalid or appears masked"):
            await ch.send(ChannelPayload(title="t", body="{}", content_type=ContentType.CARD_JSON))

    async def test_non_url_raises_readable_error(self) -> None:
        ch = self._channel("not-a-url")
        with pytest.raises(NotificationException, match="invalid or appears masked"):
            await ch.send(ChannelPayload(title="t", body="{}", content_type=ContentType.CARD_JSON))
