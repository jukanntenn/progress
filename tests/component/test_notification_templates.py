"""Snapshot-style tests for notification template output (spec 10).

Renders each event kind's three channel templates (Feishu card JSON, email HTML,
console plain text) and asserts the structural elements that must be present to
match the pre-refactor (ffd9d3c) notification layout. These guard against
regressions in the multi-element Feishu card (stats grid / hr / action button /
card_link), the branded email shell (header / metrics / status boxes / footer),
and the console plain-text summary.
"""

from __future__ import annotations

import json

import pytest

from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.templating import create_environment

_TEMPLATE_DIRS = [
    "src/progress/cli/notifications/templates",
    "src/progress/integrations/changelog/templates/notifications",
    "src/progress/integrations/feed/templates/notifications",
    "src/progress/integrations/proposal/templates/notifications",
    "src/progress/integrations/repo/templates/notifications",
]


@pytest.fixture(scope="module")
def env():
    env = create_environment(_TEMPLATE_DIRS, autoescape=False)
    env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # type: ignore
    return env


class TestReportCard:
    def test_failed_card_uses_red_header_with_stat_grid_and_cta(self, env) -> None:
        card = json.loads(
            env.get_template("repo_update/card_json.j2").render(
                title="Progress Report",
                summary="6 repos updated",
                markpost_url="https://markpost.example/r/1",
                repo_statuses={"django/django": "success", "bad/repo": "failed", "skip/repo": "skipped"},
                repo_urls={
                    "django/django": "https://github.com/django/django",
                    "bad/repo": "https://github.com/bad/repo",
                    "skip/repo": "",
                },
                total_commits=42,
            )
        )
        # v2 invariants
        assert card["schema"] == "2.0"
        assert card["config"]["width_mode"] == "fill"
        assert card["config"]["update_multi"] is True
        assert "wide_screen_mode" not in card["config"]
        # failed-state red header + FAILED badge
        assert card["header"]["template"] == "red"
        tag = card["header"]["text_tag_list"][0]
        assert "FAILED" in tag["text"]["content"]
        assert tag["color"] == "red"
        assert card["card_link"] == {"url": "https://markpost.example/r/1"}
        # body.elements (NOT top-level elements); no v1 action wrapper
        assert "elements" not in card
        elements = card["body"]["elements"]
        tags = [e["tag"] for e in elements]
        assert tags[0] == "markdown"  # overview
        assert "column_set" in tags  # stat grid
        assert "button" in tags  # CTA (v2: raw button, no action wrapper)
        assert not any(e["tag"] == "action" for e in elements)  # v2 removed action
        # the stat grid has 3 tiles (Total / Commits / Failed)
        grid = next(e for e in elements if e["tag"] == "column_set")
        assert len(grid["columns"]) == 3
        # failed column is red-tinted
        failed_col = grid["columns"][2]
        assert failed_col["background_style"] == "red-50"
        # CTA button targets markpost
        cta = next(e for e in elements if e["tag"] == "button")
        assert cta["type"] == "primary_filled"
        assert cta["behaviors"][0]["default_url"] == "https://markpost.example/r/1"

    def test_success_card_uses_green_header(self, env) -> None:
        card = json.loads(
            env.get_template("repo_update/card_json.j2").render(
                title="T",
                summary="s",
                markpost_url="",
                repo_statuses={"a/b": "success"},
                repo_urls={"a/b": "u"},
                total_commits=1,
            )
        )
        assert card["header"]["template"] == "green"
        assert "card_link" not in card  # no markpost_url → no card_link
        tag = card["header"]["text_tag_list"][0]
        assert "SUCCESS" in tag["text"]["content"]
        assert tag["color"] == "green"


class TestChangelogCard:
    def test_card_lists_entries_with_level_badges_and_markpost_cta(self, env) -> None:
        card = json.loads(
            env.get_template("changelog/card_json.j2").render(
                title="Changelog Updates",
                markpost_url="https://markpost.example/c",
                entries=[
                    {"name": "uTools", "version": "6.2.0", "url": "https://u.tools", "level": "MINOR"},
                    {"name": "bigapp", "version": "2.0.0", "url": "https://big.app", "level": "MAJOR"},
                ],
            )
        )
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "indigo"
        elements = card["body"]["elements"]
        tags = [e["tag"] for e in elements]
        # one column_set per entry, then hr + button CTA + hr + footer
        assert tags.count("column_set") == 2
        assert "button" in tags
        # MAJOR level renders a red text_tag inside the entry markdown
        major_row = elements[2]  # heading(0), col0(1), col1(2)
        major_md = major_row["columns"][0]["elements"][0]["content"]
        assert "<text_tag color='red'>MAJOR ⬆</text_tag>" in major_md


class TestProposalCard:
    def test_card_renders_table_with_status_and_kind_columns(self, env) -> None:
        card = json.loads(
            env.get_template("proposal/card_json.j2").render(
                title="Proposal Updates",
                markpost_url="https://markpost.example/p",
                proposals=[
                    {
                        "kind": "EIP",
                        "number": "1",
                        "title": "T1",
                        "old_status": "Draft",
                        "new_status": "Review",
                        "file_url": "https://eips/1",
                        "file_name": "eip-1.md",
                    },
                ],
                filenames=["eip-1.md"],
                more_count=0,
                total=1,
            )
        )
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "blue"
        table = next(e for e in card["body"]["elements"] if e["tag"] == "table")
        assert [c["name"] for c in table["columns"]] == ["proposal", "kind", "status"]
        row = table["rows"][0]
        assert row["kind"] == {"text": "EIP", "color": "blue"}
        assert row["status"]["text"] == "Draft → Review"


class TestDiscoveredRepoCard:
    def test_card_lists_repos_as_color_blocks_with_view_button(self, env) -> None:
        card = json.loads(
            env.get_template("discovered_repo/card_json.j2").render(
                title="Discovered Repos",
                markpost_url="https://markpost.example/d",
                repos=[{"name": f"r{i}", "url": f"https://x/{i}"} for i in range(7)],
            )
        )
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "turquoise"
        elements = card["body"]["elements"]
        # 5 visible repo rows as column_set, plus a collapsible for the rest
        rows = [e for e in elements if e["tag"] == "column_set"]
        assert len(rows) == 5
        panel = next(e for e in elements if e["tag"] == "collapsible_panel")
        assert "2" in panel["header"]["title"]["content"]  # remaining 2


class TestReportEmail:
    def test_email_has_branded_shell_metrics_status_boxes_footer(self, env) -> None:
        html = env.get_template("repo_update/html.j2").render(
            title="Progress Report",
            summary="6 repos updated",
            markpost_url="https://markpost.example/r/1",
            repo_statuses={"django/django": "success", "bad/repo": "failed", "skip/repo": "skipped"},
            repo_urls={
                "django/django": "https://github.com/django/django",
                "bad/repo": "https://github.com/bad/repo",
                "skip/repo": "",
            },
            total_commits=42,
        )
        assert "<!DOCTYPE html>" in html
        # red header bar (inline CSS) — failure state
        assert "background-color:#F53F3F" in html
        # header FAILED badge
        assert "FAILED" in html
        # stat tiles (Total Repositories / Total Commits / Failed)
        assert "Total Repositories" in html
        assert "Total Commits" in html
        assert "Failed Repositories" in html
        # failed repo row with View Details button
        assert "bad/repo" in html
        assert "View Details" in html
        # skipped repos fold
        assert "Skipped Repositories" in html
        # primary CTA + footer
        assert "View Detailed Report" in html
        assert "Generated by Progress" in html

    def test_email_success_uses_green_header_and_success_rate(self, env) -> None:
        html = env.get_template("repo_update/html.j2").render(
            title="T",
            summary="s",
            markpost_url="",
            repo_statuses={"a/b": "success"},
            repo_urls={"a/b": "u"},
            total_commits=1,
        )
        # green header bar — success state
        assert "background-color:#00B42A" in html
        assert "SUCCESS" in html
        assert "Success Rate" in html


class TestProposalEmail:
    def test_email_renders_table_with_kind_and_status_badges(self, env) -> None:
        html = env.get_template("proposal/html.j2").render(
            title="Proposal Updates",
            markpost_url="https://markpost.example/p",
            proposals=[
                {
                    "kind": "EIP",
                    "number": "1",
                    "title": "T1",
                    "old_status": "Draft",
                    "new_status": "Review",
                    "file_url": "https://eips/1",
                    "file_name": "eip-1.md",
                },
                {
                    "kind": "ERC",
                    "number": "2",
                    "title": "T2",
                    "old_status": "",
                    "new_status": "Draft",
                    "file_url": "https://eips/2",
                    "file_name": "erc-2.md",
                },
            ],
        )
        assert not html.lstrip().startswith("Subject:")
        # blue header bar + NEW badge
        assert "background-color:#3370FF" in html
        assert "NEW 2" in html
        # table with linked proposal, typed kind badge, status badge
        assert "#1 T1" in html
        assert "Draft → Review" in html
        assert "Draft (new)" in html
        assert "View Proposal Details" in html


class TestChangelogEmail:
    def test_email_lists_entries_with_level_badges_and_markpost_link(self, env) -> None:
        html = env.get_template("changelog/html.j2").render(
            title="Changelog Updates",
            markpost_url="https://markpost.example/c",
            entries=[
                {"name": "uTools", "version": "6.2.0", "url": "https://u.tools", "level": "MINOR"},
                {"name": "bigapp", "version": "2.0.0", "url": "https://big.app", "level": "MAJOR"},
            ],
        )
        # indigo header bar + RELEASE badge
        assert "background-color:#4080FF" in html
        assert "RELEASE 2" in html
        # version rows with level badges + Release Note buttons
        assert "uTools" in html
        assert "6.2.0" in html
        assert "MAJOR ⬆" in html
        assert "Release Note" in html
        assert "View Full Changelog" in html


class TestDiscoveredRepoEmail:
    def test_email_lists_top5_with_view_buttons_and_more(self, env) -> None:
        html = env.get_template("discovered_repo/html.j2").render(
            title="Discovered Repos",
            markpost_url="https://markpost.example/d",
            repos=[{"name": f"r{i}", "url": f"https://x/{i}"} for i in range(7)],
        )
        # turquoise header bar + NEW badge
        assert "background-color:#14C9C9" in html
        assert "NEW 7" in html
        assert "📦 r0" in html
        assert "📦 r4" in html
        assert "Expand remaining" in html
        assert "View Discovery Details" in html


class TestFeedCard:
    """Feishu v2 card for the feed integration (spec feed §8.3.1, v2 redesign)."""

    def test_card_renders_color_block_feed_grid_with_markpost_cta(self, env) -> None:
        card = json.loads(
            env.get_template("feed/card_json.j2").render(
                title="RSS Digest",
                summary="s",
                markpost_url="https://markpost.example/f",
                feeds=[
                    {"title": "Hacker News", "entry_count": 3, "url": "https://news.ycombinator.com"},
                    {"title": "Lobsters", "entry_count": 2, "url": "https://lobste.rs"},
                ],
                feed_count=2,
                entry_count=5,
                batch_index=0,
                total_batches=1,
                run_at="2026-07-25 10:00:00 UTC",
            )
        )
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "wathet"
        # no v1 note element; footer uses markdown + <font>
        elements = card["body"]["elements"]
        assert not any(e["tag"] == "note" for e in elements)
        # each feed is a blue-tinted color-block column with a big number
        grid = next(e for e in elements if e["tag"] == "column_set")
        assert len(grid["columns"]) == 2
        assert grid["columns"][0]["background_style"] == "blue-50"
        # footer contains run_at
        footer = elements[-1]
        assert footer["tag"] == "markdown"
        assert "2026-07-25 10:00:00 UTC" in footer["content"]

    def test_card_single_feed_markpost_cta(self, env) -> None:
        card = json.loads(
            env.get_template("feed/card_json.j2").render(
                title="t",
                summary="s",
                markpost_url="https://markpost.example/f",
                feeds=[{"title": "Only", "entry_count": 1, "url": ""}],
                feed_count=1,
                entry_count=1,
                batch_index=0,
                total_batches=1,
                run_at="x",
            )
        )
        elements = card["body"]["elements"]
        grid = next(e for e in elements if e["tag"] == "column_set")
        assert len(grid["columns"]) == 1  # single feed → one column
        assert "card_link" in card


class TestFeedPlainText:
    def test_plain_text_is_title_plus_url(self, env) -> None:
        text = env.get_template("feed/plain_text.j2").render(
            title="RSS Digest",
            summary="s",
            markpost_url="https://markpost.example/f",
            feeds=[],
            feed_count=0,
            entry_count=0,
        )
        # feeber format_console_text: "{title}\n\n{url}"
        assert text == "RSS Digest\n\nhttps://markpost.example/f"

    def test_plain_text_no_url(self, env) -> None:
        text = env.get_template("feed/plain_text.j2").render(
            title="RSS Digest",
            markpost_url="",
            feeds=[],
            feed_count=0,
            entry_count=0,
        )
        assert text == "RSS Digest"


class TestFeedEmail:
    def test_email_lists_feeds_with_counts_and_link(self, env) -> None:
        html = env.get_template("feed/html.j2").render(
            title="RSS Digest",
            summary="overview",
            markpost_url="https://markpost.example/f",
            feeds=[
                {"title": "Hacker News", "entry_count": 3},
                {"title": "Lobsters", "entry_count": 2},
            ],
            feed_count=2,
            entry_count=5,
            batch_index=0,
            total_batches=1,
        )
        # wathet header bar + N new badge
        assert "background-color:#0091FF" in html
        assert "RSS Digest" in html
        assert "overview" in html
        # feed tiles with counts
        assert "Hacker News" in html
        assert "Lobsters" in html
        assert "new articles" in html
        assert "View Full Digest" in html
