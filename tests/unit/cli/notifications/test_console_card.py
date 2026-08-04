"""Unit tests for the console rich-card renderer (``console_card.py``).

Focuses on the two refactors (spec 10):

1. **Single source of truth** — status color/label come from
   :mod:`progress.cli.notifications.status`, so the console card no longer
   keeps a parallel local mapping that could drift from the templates.
2. **Flat list** — every item renders (no ``[:5]`` fold) and the decorative
   ``▸ Expand remaining`` marker is gone; only Feishu keeps a real
   ``collapsible_panel``.
"""

from __future__ import annotations

import io

from rich.console import Console as RichConsole

from progress.cli.notifications.base import ChannelPayload, ContentType
from progress.cli.notifications.channels.console_card import render_console_card
from progress.cli.notifications.events import NotificationEvent


def _render_to_text(event: NotificationEvent) -> str:
    """Render the console card for ``event`` and capture it as flat text."""
    payload = ChannelPayload(
        title=event.title,
        body="",
        content_type=ContentType.PLAIN_TEXT,
        metadata={"event": event},
    )
    card = render_console_card(payload)
    assert card is not None, "render_console_card returned None for a known kind"
    buf = io.StringIO()
    RichConsole(file=buf, force_terminal=False, width=80, record=True).print(card)
    return buf.getvalue()


class TestRepoUpdateFlat:
    def test_lists_all_success_repos_without_fold(self) -> None:
        event = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="",
            data={
                "repo_statuses": {f"ok/repo-{i}": "success" for i in range(8)},
                "repo_urls": {f"ok/repo-{i}": f"https://x/{i}" for i in range(8)},
                "total_commits": 0,
            },
        )
        out = _render_to_text(event)
        for i in range(8):
            assert f"ok/repo-{i}" in out
        assert "Expand remaining" not in out

    def test_lists_all_skipped_repos_without_fold(self) -> None:
        event = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="",
            data={
                "repo_statuses": {f"skip/repo-{i}": "skipped" for i in range(7)},
                "repo_urls": {f"skip/repo-{i}": "" for i in range(7)},
                "total_commits": 0,
            },
        )
        out = _render_to_text(event)
        for i in range(7):
            assert f"skip/repo-{i}" in out

    def test_status_badges_render_via_single_source(self) -> None:
        # English locale: SUCCESS/FAILED/SKIPPED labels come from status_label.
        # A failure present routes to the failed branch (failed + skipped
        # shown); success-only repos render under the success branch.
        event_fail = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="",
            data={
                "repo_statuses": {"b/failed": "failed", "c/skipped": "skipped"},
                "repo_urls": {"b/failed": "", "c/skipped": ""},
                "total_commits": 0,
            },
        )
        out_fail = _render_to_text(event_fail)
        assert "FAILED" in out_fail
        assert "SKIPPED" in out_fail

        event_ok = NotificationEvent(
            kind="repo_update",
            title="t",
            summary="s",
            markpost_url="",
            data={
                "repo_statuses": {"a/success": "success"},
                "repo_urls": {"a/success": ""},
                "total_commits": 0,
            },
        )
        out_ok = _render_to_text(event_ok)
        assert "SUCCESS" in out_ok


class TestProposalFlat:
    def test_lists_all_proposals_without_fold(self) -> None:
        event = NotificationEvent(
            kind="proposal",
            title="t",
            summary="",
            markpost_url="",
            data={
                "proposals": [
                    {
                        "kind": "EIP",
                        "number": str(i),
                        "title": f"T{i}",
                        "old_status": "",
                        "new_status": "Draft",
                        "file_url": "",
                        "file_name": f"eip-{i}.md",
                    }
                    for i in range(8)
                ],
            },
        )
        out = _render_to_text(event)
        for i in range(8):
            assert f"#{i} T{i}" in out
        assert "Expand remaining" not in out


class TestChangelogFlat:
    def test_lists_all_versions_without_fold(self) -> None:
        event = NotificationEvent(
            kind="changelog",
            title="t",
            summary="",
            markpost_url="",
            data={
                "entries": [{"name": f"pkg-{i}", "version": f"1.{i}.0", "url": "", "level": "PATCH"} for i in range(9)],
            },
        )
        out = _render_to_text(event)
        for i in range(9):
            assert f"pkg-{i}" in out
        assert "Expand remaining" not in out


class TestDiscoveredRepoFlat:
    def test_lists_all_repos_without_fold(self) -> None:
        event = NotificationEvent(
            kind="discovered_repo",
            title="t",
            summary="",
            markpost_url="",
            data={"repos": [{"name": f"r{i}", "url": ""} for i in range(6)]},
        )
        out = _render_to_text(event)
        for i in range(6):
            assert f"r{i}" in out
        assert "Expand remaining" not in out


class TestRenderDefensive:
    def test_unknown_kind_returns_none(self) -> None:
        event = NotificationEvent(kind="never_heard_of_it", title="t", data={})
        payload = ChannelPayload(title="t", body="", content_type=ContentType.PLAIN_TEXT, metadata={"event": event})
        assert render_console_card(payload) is None

    def test_missing_event_returns_none(self) -> None:
        payload = ChannelPayload(title="t", body="", content_type=ContentType.PLAIN_TEXT)
        assert render_console_card(payload) is None

    def test_render_never_raises_on_bad_data(self) -> None:
        # A bogus data shape must not crash delivery — the renderer swallows
        # and returns None so the channel falls back to the plain body.
        event = NotificationEvent(kind="repo_update", title="t", data={"repo_statuses": "not-a-dict"})
        payload = ChannelPayload(title="t", body="", content_type=ContentType.PLAIN_TEXT, metadata={"event": event})
        assert render_console_card(payload) is None
