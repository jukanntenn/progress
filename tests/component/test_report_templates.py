"""Snapshot-style tests for report section templates (spec 09).

Asserts the structural elements each report template must emit to match the
pre-refactor (ffd9d3c) layout: repo report badges/release summary/AI fallback,
discovered-repo report heading/date badge/blockquote, and proposal report badge.
Guards against drift in the report markdown that gets persisted and published.
"""

from __future__ import annotations

from jinja2 import StrictUndefined
import pytest

from progress.cli.notifications.status import status_label
from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.templating import create_environment

_TEMPLATE_DIRS = [
    "src/progress/cli/reports/templates/reports",
    "src/progress/integrations/repo/templates",
    "src/progress/integrations/changelog/templates",
    "src/progress/integrations/feed/templates",
    "src/progress/integrations/proposal/templates",
    "src/progress/integrations/v2ex/templates",
]


@pytest.fixture(scope="module")
def env():
    env = create_environment(_TEMPLATE_DIRS, autoescape=False, undefined=StrictUndefined)
    env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # type: ignore
    env.globals.update({"status_label": status_label})  # type: ignore
    return env


class TestRepoReport:
    def test_heading_has_branch_commit_badge_on_own_line(self, env) -> None:
        out = env.get_template("repo_report.j2").render(
            repo_name="django/django",
            repo_web_url="https://github.com/django/django",
            branch="main",
            commit_count=5,
            releases=[],
            commits=[],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "## [django/django](https://github.com/django/django)" in out
        assert "🌿 `main`" in out
        assert "✏️ 5" in out
        assert "commits" in out

    def test_release_summary_has_rocket_tag_emojis(self, env) -> None:
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=0,
            releases=[
                {
                    "name": "5.0",
                    "tag": "5.0",
                    "notes_html": "<p>n</p>",
                    "ai_summary": "[AI-SUMMARY]",
                    "ai_detail": "det",
                    "published_at": "",
                }
            ],
            commits=[],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "🚀 5.0 🏷️ 5.0" in out
        assert "Click to view detailed release analysis" in out
        # AI summary must be OUTSIDE the release <details> (always visible)
        assert "[AI-SUMMARY]" in out
        assert out.index("</details>") < out.index("[AI-SUMMARY]")

    def test_truncation_warning_is_small_tag(self, env) -> None:
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "msg", "body": ""}],
            analysis_summary="",
            analysis_detail="",
            truncated=True,
            original_diff_length=1000,
            analyzed_diff_length=200,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "<small>⚠️" in out
        assert "Diff truncated" in out
        assert "1000 → 200" in out
        assert "chars" in out

    def test_analysis_summary_falls_back_when_empty(self, env) -> None:
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "msg", "body": ""}],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "**AI analysis unavailable**" in out

    def test_single_line_commit_renders_div(self, env) -> None:
        """Feature 2: a bodyless commit renders as a flat <div>, not <details>."""
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "fix: typo", "body": ""}],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "<div>fix: typo</div>" in out
        assert "<details>" not in out.split("<div>fix: typo</div>")[0].rsplit("<small>", 1)[-1]

    def test_multi_line_commit_renders_details(self, env) -> None:
        """Feature 3: a commit with a body renders as <details><summary>subject</summary>body."""
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "feat: add X", "body": "Detailed body line"}],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "<details>" in out
        assert "<summary>feat: add X</summary>" in out
        assert "Detailed body line" in out

    def test_squash_duplicate_renders_subject_once(self, env) -> None:
        """Feature 2: a squash-duplicate (body already collapsed) shows the subject once."""
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "Same", "body": ""}],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert out.count("Same") == 1
        assert "<div>Same</div>" in out

    def test_commit_subject_html_escaped(self, env) -> None:
        """Security: commit subject is HTML-escaped (external data)."""
        out = env.get_template("repo_report.j2").render(
            repo_name="r",
            repo_web_url="https://github.com/r",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "<script>x</script>", "body": ""}],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
            releases_truncated=False,
            releases_total_available=0,
        )
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_failed_repo_renders_failure_banner(self, env) -> None:
        """Regression: a repo whose diff failed (status='failed') must render a
        ❌ banner with the failure_reason, not a bare heading. Previously the
        template ignored status/failure_reason entirely, so apache/airflow
        showed up as an empty ``##`` section."""
        out = env.get_template("repo_report.j2").render(
            repo_name="apache/airflow",
            repo_web_url="https://github.com/apache/airflow.git",
            branch="main",
            commit_count=0,
            releases=[],
            commits=[],
            analysis_summary="",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="failed",
            failure_reason="bad object: abc123",
        )
        assert "## [apache/airflow]" in out
        assert "❌" in out
        assert "Tracking failed" in out
        assert "bad object: abc123" in out
        # No spurious commit/release block when the repo failed with no commits
        assert "commits" not in out

    def test_success_repo_has_no_failure_banner(self, env) -> None:
        """A successful repo must NOT render the failure banner."""
        out = env.get_template("repo_report.j2").render(
            repo_name="ok/repo",
            repo_web_url="https://github.com/ok/repo",
            branch="main",
            commit_count=1,
            releases=[],
            commits=[{"subject": "feat: x", "body": ""}],
            analysis_summary="summary",
            analysis_detail="",
            truncated=False,
            original_diff_length=0,
            analyzed_diff_length=0,
            status="success",
        )
        assert "Tracking failed" not in out
        assert "❌" not in out


class TestRepoNewReport:
    def test_heading_date_badge_blockquote(self, env) -> None:
        out = env.get_template("repo_new_report.j2").render(
            new_repos=[
                {
                    "name": "alice/repo1",
                    "url": "https://github.com/alice/repo1",
                    "description": "a repo",
                    "readme_summary": "rm sum",
                    "readme_detail": "rm detail",
                    "discovered_at": "2026-07-23 10:00:00",
                }
            ],
        )
        assert "Discovered repository" not in out
        assert "### [alice/repo1](https://github.com/alice/repo1)" in out
        assert "🗓️ 2026-07-23 10:00:00" in out
        assert "> a repo" in out
        assert "Click to view detailed analysis" in out


class TestProposalReport:
    def test_badge_has_status_transition_and_filename(self, env) -> None:
        out = env.get_template("proposal_report.j2").render(
            kind="eip",
            tracker_url="https://github.com/ethereum/EIPs",
            reports=[
                {
                    "number": 1,
                    "title": "Fixed supply",
                    "old_status": "draft",
                    "new_status": "final",
                    "file_path": "EIPS/eip-1.md",
                    "file_url": "https://github.com/ethereum/EIPs/blob/x/EIPS/eip-1.md",
                    "analysis_summary": "sum",
                    "analysis_detail": "det",
                }
            ],
        )
        assert "## [EIP](https://github.com/ethereum/EIPs)" in out
        assert "#️⃣ #1" in out
        # status renders via status_label (msgid keys in the en catalog)
        assert "proposal_status_draft → proposal_status_final" in out
        assert "📄 eip-1.md" in out
        assert "Click to view detailed analysis" in out

    def test_no_footer_in_section(self, env) -> None:
        out = env.get_template("proposal_report.j2").render(
            kind="eip",
            tracker_url="",
            reports=[],
        )
        assert "Generated by" not in out


class TestFeedReport:
    def test_heading_summary_and_entries(self, env) -> None:
        out = env.get_template("feed_report.j2").render(
            feed_title="Hacker News",
            site_url="https://news.ycombinator.com",
            summary="Feed-level AI summary",
            entries=[
                {
                    "title": "Entry One",
                    "url": "https://example.com/1",
                    "published_at": "2026-07-25 10:00:00",
                    "analysis": "Per-entry analysis",
                }
            ],
        )
        assert "## [Hacker News](https://news.ycombinator.com)" in out
        assert "Feed-level AI summary" in out
        # legacy feeber format: one outer <details> wrapping entries, non-bold linked title
        assert "<summary>Click to read 1 entry</summary>" in out
        assert "[Entry One](https://example.com/1)" in out
        assert "**[Entry One]" not in out
        # published_at is intentionally NOT shown (matches old feeber source_section.j2)
        assert "2026-07-25 10:00:00" not in out
        assert "Per-entry analysis" in out

    def test_entry_separator_between_entries(self, env) -> None:
        out = env.get_template("feed_report.j2").render(
            feed_title="Feed",
            site_url="",
            summary="s",
            entries=[
                {"title": "A", "url": "https://a", "published_at": "t", "analysis": "aa"},
                {"title": "B", "url": "https://b", "published_at": "t", "analysis": "bb"},
            ],
        )
        assert "<summary>Click to read 2 entries</summary>" in out
        # --- separates entries, but NOT after the last one
        assert out.count("\n---\n") == 1

    def test_heading_without_site_url(self, env) -> None:
        out = env.get_template("feed_report.j2").render(
            feed_title="No Site",
            site_url="",
            summary="s",
            entries=[],
        )
        assert "## No Site" in out
        assert "## [No Site]" not in out

    def test_external_titles_are_escaped(self, env) -> None:
        out = env.get_template("feed_report.j2").render(
            feed_title="<b>feed</b>",
            site_url="",
            summary="s",
            entries=[{"title": "<script>x</script>", "url": "", "published_at": "t", "analysis": ""}],
        )
        # autoescape=False, so titles MUST be manually escaped with | e
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_no_footer_in_section(self, env) -> None:
        out = env.get_template("feed_report.j2").render(
            feed_title="x",
            site_url="",
            summary="s",
            entries=[],
        )
        assert "Generated by" not in out


class TestV2exReport:
    """Per-post layout: linked title → node·author badge → bare reason
    blockquote → takeaway paragraph → collapsible original post. Score/replies
    are internal selection signals and must not appear."""

    def _post(self, **overrides: object) -> dict[str, object]:
        post: dict[str, object] = {
            "title": "Rust 后端岗位",
            "url": "https://v2ex.com/t/100",
            "node": "酷工作",
            "author": "alice",
            "replies": 23,
            "score": 9,
            "reason": "涉及 Rust 异步生态\n命中基础设施画像",
            "takeaway": "AI 分析正文",
            "content": "原文第一段\n\n```rust\nfn x() {}\n```",
            "content_truncated": False,
            "created_at": "2026-08-12T02:00:00+00:00",
        }
        post.update(overrides)
        return post

    def _render(self, env, posts: list[dict[str, object]]) -> str:
        return env.get_template("v2ex_report.j2").render(
            tab_title="酷工作",
            tab_url="https://v2ex.com/?tab=jobs",
            posts=posts,
        )

    def test_quote_takeaway_details_layout(self, env) -> None:
        out = self._render(env, [self._post()])
        assert "### [Rust 后端岗位](https://v2ex.com/t/100)" in out
        assert "🏷️ 酷工作 · 👤 alice" in out
        # reason as a bare blockquote, every line prefixed, no label copy
        assert "> 涉及 Rust 异步生态" in out
        assert "> 命中基础设施画像" in out
        assert "Why selected" not in out
        # takeaway directly after the quote, no label copy
        assert "\nAI 分析正文" in out
        # original post inside a collapsed details
        assert "<details>" in out
        assert "<summary>View original post</summary>" in out
        assert "```rust" in out
        assert out.index("> 命中基础设施画像") < out.index("AI 分析正文") < out.index("<details>")

    def test_score_and_replies_never_rendered(self, env) -> None:
        out = self._render(env, [self._post()])
        assert "⭐" not in out and "💬" not in out
        assert "23" not in out and " 9" not in out

    def test_truncation_marker_only_when_truncated(self, env) -> None:
        out = self._render(env, [self._post(content_truncated=True)])
        assert "Original truncated" in out
        out = self._render(env, [self._post()])
        assert "Original truncated" not in out

    def test_posts_separated_by_rule(self, env) -> None:
        out = self._render(env, [self._post(), self._post(title="第二个")])
        assert "\n---\n" in out

    def test_external_metadata_is_escaped(self, env) -> None:
        out = self._render(env, [self._post(title="<script>t</script>", author="a<b>")])
        assert "<script>t</script>" not in out
        assert "&lt;script&gt;t&lt;/script&gt;" in out
