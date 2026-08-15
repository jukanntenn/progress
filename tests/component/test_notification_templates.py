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
from pathlib import Path
import re

import pytest

from progress.cli.notifications.status import status_color, status_icon, status_label
from progress.utils.i18n import gettext as _, ngettext, npgettext, override, pgettext
from progress.utils.templating import create_environment

_TEMPLATE_DIRS = [
    "src/progress/cli/notifications/templates",
    "src/progress/integrations/changelog/templates/notifications",
    "src/progress/integrations/feed/templates/notifications",
    "src/progress/integrations/proposal/templates/notifications",
    "src/progress/integrations/repo/templates/notifications",
    "src/progress/integrations/v2ex/templates/notifications",
]


@pytest.fixture(scope="module")
def env():
    env = create_environment(_TEMPLATE_DIRS, autoescape=False)
    env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # type: ignore
    # Mirror JinjaRenderer._get_env: expose the status single-source lookups so
    # templates resolve status color/icon/label from one place (spec 10).

    env.globals.update({"status_color": status_color, "status_icon": status_icon, "status_label": status_label})  # type: ignore
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
        assert "View Report" in html
        assert "Generated by" in html

    def test_email_success_uses_green_header_and_updated_repos(self, env) -> None:
        html = env.get_template("repo_update/html.j2").render(
            title="T",
            summary="s",
            markpost_url="",
            repo_statuses={"a/b": "success"},
            repo_urls={"a/b": "u"},
            total_commits=1,
            repos_with_updates=1,
        )
        # green header bar — success state
        assert "background-color:#00B42A" in html
        assert "SUCCESS" in html
        assert "Updated Repos" in html


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
        assert "View Report" in html


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
        assert "View Report" in html


class TestDiscoveredRepoEmail:
    def test_email_lists_all_repos_flat_with_view_links(self, env) -> None:
        html = env.get_template("discovered_repo/html.j2").render(
            title="Discovered Repos",
            markpost_url="https://markpost.example/d",
            repos=[{"name": f"r{i}", "url": f"https://x/{i}"} for i in range(7)],
        )
        # turquoise header bar + NEW badge
        assert "background-color:#14C9C9" in html
        assert "NEW 7" in html
        # flat layout (spec 10): every repo renders, no [:5] fold, no fake
        # "Expand remaining" marker in email (only Feishu keeps a real fold).
        for i in range(7):
            assert f"📦 r{i}" in html
        assert "Expand remaining" not in html
        assert "View Report" in html


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
                generated_at="2026-07-25 10:00:00 UTC",
            )
        )
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "wathet"
        # no v1 note element; footer uses markdown + <font>
        elements = card["body"]["elements"]
        assert not any(e["tag"] == "note" for e in elements)
        # two-column grid (bisect): the two feeds render as one equal row
        grids = [e for e in elements if e["tag"] == "column_set"]
        assert len(grids) == 1
        assert len(grids[0]["columns"]) == 2
        assert grids[0]["flex_mode"] == "bisect"
        assert grids[0]["columns"][0]["background_style"] == "blue-50"
        # footer is the last element and carries the per-render timestamp
        footer = elements[-1]
        assert footer["tag"] == "markdown"
        assert footer["text_align"] == "center"
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
        assert "View Report" in html


class TestV2exCard:
    """High-density v2ex digest (spec v2ex §10): AI summary + per-tab counts +
    top-post one-liners (score/replies). Takeaways stay in the report — the
    card must never duplicate them."""

    def _vars(self) -> dict[str, object]:
        return {
            "title": "V2EX Digest",
            "summary": "three picks",
            "markpost_url": "https://markpost.example/v/1",
            "tabs": [
                {"tab_title": "热门", "icon": "🔥", "count": 2},
                {"tab_title": "技术", "icon": "⚙", "count": 1},
            ],
            "top_posts": [
                {"title": "Rust const generics", "url": "https://v2ex.com/t/1", "score": 9, "replies": 156},
                {"title": "Go 1.24 stacks", "url": "https://v2ex.com/t/2", "score": 8, "replies": 89},
                {"title": "RPi5 NPU", "url": "https://v2ex.com/t/3", "score": 8, "replies": 47},
            ],
            "selected_count": 3,
            "generated_at": "2026-08-15 15:04:00 CST",
        }

    def test_card_renders_counts_top_posts_and_cta(self, env) -> None:
        card = json.loads(env.get_template("v2ex/card_json.j2").render(**self._vars()))
        assert card["schema"] == "2.0"
        blob = json.dumps(card, ensure_ascii=False)
        assert "three picks" in blob
        # per-tab count badges + top-post one-liners with score/replies
        assert "热门" in blob and "技术" in blob
        assert "Rust const generics" in blob
        assert "⭐9" in blob and "💬156" in blob
        assert "takeaway" not in blob
        # CTA + footer
        assert card["card_link"]["url"] == "https://markpost.example/v/1"
        assert any(e.get("tag") == "button" for e in card["body"]["elements"])
        assert "2026-08-15 15:04:00 CST" in blob

    def test_email_renders_dense_list_with_cta(self, env) -> None:
        html = env.get_template("v2ex/html.j2").render(**self._vars())
        assert "three picks" in html
        assert "热门" in html
        assert 'href="https://v2ex.com/t/1"' in html
        assert "⭐ 9" in html and "💬 156" in html
        assert "View Report" in html
        assert "takeaway" not in html

    def test_plain_text_is_one_liner_digest(self, env) -> None:
        text = env.get_template("v2ex/plain_text.j2").render(**self._vars())
        assert "3 picks" in text
        assert "🔥 热门 2 · ⚙ 技术 1" in text
        assert "1. Rust const generics ⭐9 💬156" in text
        assert "Full report → https://markpost.example/v/1" in text


class TestStatusSingleSourceConsistency:
    """The pre-refactor production bug was a status→label drift (``Successful
    Repositories`` translated to ``失败的仓库``) that shipped because the status
    mapping was duplicated across 6+ sites with nothing keeping them honest.
    These tests make the single-source contract structural: templates must
    resolve status color/icon/label from
    :mod:`progress.cli.notifications.status`, not from a local dict."""

    def test_repo_card_json_uses_canonical_status_color(self, env) -> None:
        # failed-state card: the failed repo's text_tag color comes from the
        # single source (red). Skipped repos fold into a collapsible_panel and
        # carry the canonical grey. tojson escapes the single quotes, so we
        # parse the JSON and walk the structure rather than substring-match.
        rendered = env.get_template("repo_update/card_json.j2").render(
            title="t",
            summary="s",
            markpost_url="",
            repo_statuses={"bad/repo": "failed", "skip/repo": "skipped"},
            repo_urls={"bad/repo": "", "skip/repo": ""},
            total_commits=0,
        )
        blob = json.dumps(json.loads(rendered))
        assert "color='red'" in blob.replace("\\u0027", "'")  # failed repo badge
        assert "color='grey'" in blob.replace("\\u0027", "'")  # skipped repo badge

    def test_repo_card_json_success_uses_green_from_single_source(self, env) -> None:
        rendered = env.get_template("repo_update/card_json.j2").render(
            title="t",
            summary="s",
            markpost_url="",
            repo_statuses={"ok/repo": "success"},
            repo_urls={"ok/repo": ""},
            total_commits=0,
        )
        blob = json.dumps(json.loads(rendered))
        assert "color='green'" in blob.replace("\\u0027", "'")  # success repo badge

    def test_no_template_hardcodes_status_palette_dict(self) -> None:
        """Structural guard: no .j2 template re-introduces a hardcoded
        ``{"success": "green", ...}`` style palette dict. They must resolve
        through the status_color() global."""

        root = Path("src/progress")
        templates = list(root.glob("cli/notifications/templates/**/*.j2"))
        templates += list(root.glob("integrations/*/templates/notifications/**/*.j2"))
        assert templates, "expected notification templates to be found"
        offenders: list[str] = []
        banned = [
            '"success": "green"',
            '"failed": "red"',
            '"skipped": "grey"',
            '"MAJOR": "red"',
            '"Final": "green"',
        ]
        for tpl in templates:
            text = tpl.read_text(encoding="utf-8")
            offenders.extend(f"{tpl}: still contains `{sig}`" for sig in banned if sig in text)
        assert not offenders, "templates must resolve status colors via status_color():\n" + "\n".join(offenders)


class TestFlatListNoFakeCollapse:
    """Email/console must render every item flat (no [:5] fold, no decorative
    ``▸ Expand remaining`` marker) — only Feishu keeps a real
    ``collapsible_panel``. This is the layout fix (spec 10): the ``▸`` marker
    was a non-interactive lie in email/console since the content was already
    listed below it."""

    def test_repo_update_email_lists_all_success_repos_without_fold(self, env) -> None:
        names = {f"ok/repo-{i}": "success" for i in range(8)}
        html = env.get_template("repo_update/html.j2").render(
            title="t",
            summary="s",
            markpost_url="",
            repo_statuses=names,
            repo_urls=dict.fromkeys(names, ""),
            total_commits=0,
        )
        for i in range(8):
            assert f"ok/repo-{i}" in html, f"success repo {i} was folded away"
        assert "Expand remaining" not in html

    def test_repo_update_email_lists_all_skipped_repos_without_fold(self, env) -> None:
        names = {f"skip/repo-{i}": "skipped" for i in range(7)}
        html = env.get_template("repo_update/html.j2").render(
            title="t",
            summary="s",
            markpost_url="",
            repo_statuses=names,
            repo_urls=dict.fromkeys(names, ""),
            total_commits=0,
        )
        for i in range(7):
            assert f"skip/repo-{i}" in html

    def test_proposal_email_lists_all_proposals_without_fold(self, env) -> None:
        proposals = [
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
        ]
        html = env.get_template("proposal/html.j2").render(
            title="t",
            markpost_url="",
            proposals=proposals,
        )
        for i in range(8):
            assert f"#{i} T{i}" in html
        assert "Expand remaining" not in html

    def test_changelog_email_lists_all_versions_without_fold(self, env) -> None:
        entries = [{"name": f"pkg-{i}", "version": f"1.{i}.0", "url": "", "level": "PATCH"} for i in range(9)]
        html = env.get_template("changelog/html.j2").render(
            title="t",
            markpost_url="",
            entries=entries,
        )
        for i in range(9):
            assert f"pkg-{i}" in html
        assert "Expand remaining" not in html

    def test_discovered_repo_email_lists_all_repos_without_fold(self, env) -> None:
        repos = [{"name": f"r{i}", "url": ""} for i in range(6)]
        html = env.get_template("discovered_repo/html.j2").render(
            title="t",
            markpost_url="",
            repos=repos,
        )
        for i in range(6):
            assert f"r{i}" in html
        assert "Expand remaining" not in html

    def test_feishu_card_keeps_real_collapsible_panel(self, env) -> None:
        """Feishu is the one channel that should still fold (real
        ``collapsible_panel``), because card width is constrained."""
        card = json.loads(
            env.get_template("repo_update/card_json.j2").render(
                title="t",
                summary="s",
                markpost_url="",
                repo_statuses={f"ok/r-{i}": "success" for i in range(8)},
                repo_urls={f"ok/r-{i}": "" for i in range(8)},
                total_commits=0,
            )
        )
        panels = [e for e in card["body"]["elements"] if e.get("tag") == "collapsible_panel"]
        assert panels, "Feishu card must keep its real collapsible_panel for overflow"


class TestEmailLayoutNoButtonOverflow:
    """The pre-refactor ``info_row`` used a fixed ``width="80%" / 6px /
    width="20%"`` three-column split: the 20% button column (~109px) was
    narrower than the ``View Details`` button needed (~116px), so the button
    overflowed the right edge in narrow clients. After the refactor every row
    is a single adaptive cell with an inline action link."""

    def test_info_row_has_no_fixed_width_button_column(self) -> None:

        macro = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "progress"
            / "cli"
            / "notifications"
            / "templates"
            / "_email.j2"
        ).read_text(encoding="utf-8")
        # The banned fixed-width split that caused overflow.
        assert 'width="80%"' not in macro
        assert 'width="20%"' not in macro
        # The action is now an inline text link, not a bordered block button.

        info_row_match = re.search(r"macro info_row.*?endmacro", macro, re.DOTALL)
        assert info_row_match
        assert "border:1px solid #E5E6EB" not in info_row_match.group(0)

    def test_repo_update_email_renders_action_as_inline_link(self, env) -> None:
        html = env.get_template("repo_update/html.j2").render(
            title="t",
            summary="s",
            markpost_url="",
            repo_statuses={"bad/repo": "failed"},
            repo_urls={"bad/repo": "https://github.com/bad/repo"},
            total_commits=1,
        )
        # The failed row shows an inline "View Details" link, not a fixed
        # 20%-column bordered button.
        assert "View Details" in html


class TestChineseTranslationCorrectness:
    """The pre-refactor production bug: ``Successful Repositories`` and
    ``Newly Discovered Repositories`` were both mistranslated to
    ``失败的仓库`` ("Failed Repositories"), and ``Success Rate`` was truncated
    to ``成功``. These prove the catalogs are now correct in zh-Hans."""

    def test_successful_repositories_translation(self, env) -> None:

        with override("zh-hans"):
            html = env.get_template("repo_update/html.j2").render(
                title="t",
                summary="s",
                markpost_url="",
                repo_statuses={"a/b": "success"},
                repo_urls={"a/b": "u"},
                total_commits=1,
                repos_with_updates=1,
            )
        assert "成功的仓库" in html
        assert "失败的仓库" not in html  # the bug
        assert "有更新的仓库" in html  # replaced the old "成功率"/"Success Rate"

    def test_newly_discovered_repositories_translation(self, env) -> None:
        # The section heading "Newly Discovered Repositories" was removed; the
        # card title already conveys this. Only per-repo rows remain.
        with override("zh-hans"):
            html = env.get_template("discovered_repo/html.j2").render(
                title="t",
                markpost_url="",
                repos=[{"name": "x", "url": ""}],
            )
        assert "新发现的仓库" not in html  # heading removed
        assert "失败的仓库" not in html  # the bug
