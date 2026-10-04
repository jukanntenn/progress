"""Unit tests for the V2EX HTML parser (spec v2ex §2, test decisions).

Pure-function: ``parse_tab_page`` turns a tab page into ``RawTopic`` records.
Uses the sanitized real V2EX jobs fixture for selector realism, plus a crafted
synthetic cell for the 0-reply / missing-field edges (the captured fixtures
happen to contain no 0-reply topic).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from progress.integrations.v2ex.parser import parse_tab_page

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "v2ex"


def _jobs_html() -> str:
    return (FIXTURES / "jobs.html").read_text(encoding="utf-8")


class TestRealFixture:
    def test_parses_fifty_topics(self) -> None:
        topics = parse_tab_page(_jobs_html(), source="tab:jobs")
        assert len(topics) == 50

    def test_first_topic_fields(self) -> None:
        topics = parse_tab_page(_jobs_html(), source="tab:jobs")
        first = topics[0]
        assert first.source == "tab:jobs"
        assert first.topic_id > 0
        assert first.title  # non-empty, decoded plain text
        assert first.node_slug == "career"
        assert first.node_name == "职场话题"
        assert first.author.startswith("user_")  # sanitized
        assert first.replies >= 0
        assert first.url == f"https://www.v2ex.com/t/{first.topic_id}"
        assert first.created_at.tzinfo is not None  # aware

    def test_timestamps_are_utc_aware(self) -> None:
        topics = parse_tab_page(_jobs_html(), source="tab:jobs")
        for t in topics:
            assert t.created_at.tzinfo == UTC

    def test_html_entities_decoded(self) -> None:
        # the captured fixture contains titles with full-width quotes / ampersands;
        # parser must yield plain text, never raw HTML entities or tags.
        topics = parse_tab_page(_jobs_html(), source="tab:jobs")
        for t in topics:
            assert "&amp;" not in t.title
            assert "&quot;" not in t.title
            assert "<" not in t.title

    def test_last_replier_present_when_replies(self) -> None:
        topics = parse_tab_page(_jobs_html(), source="tab:jobs")
        replied = [t for t in topics if t.replies > 0]
        assert replied, "fixture expected to contain replied topics"
        for t in replied:
            assert t.last_replier.startswith("user_")


SYNTHETIC_PAGE = """\
<html><body>
<div class="cell item">
  <table><tr>
    <td><span class="item_title"><a href="/t/1000001#reply0" class="topic-link" id="topic-link-1000001">零回复的帖子</a></span>
      <span class="topic_info"><a class="node" href="/go/jobs">酷工作</a> •
      <strong><a href="/member/user_010">user_010</a></strong> •
      <span title="2026-08-12 09:00:00 +08:00">刚刚</span></span></td>
  </tr></table>
</div>
<div class="cell item">
  <table><tr>
    <td><span class="item_title"><a href="/t/1000002#reply3" class="topic-link" id="topic-link-1000002">有回复的帖子</a></span>
      <span class="topic_info"><a class="node" href="/go/career">职场话题</a> •
      <strong><a href="/member/user_011">user_011</a></strong> •
      <span title="2026-08-12 09:05:00 +08:00">5 分钟前</span> •
      最后回复来自 <strong><a href="/member/user_012">user_012</a></strong></span></td>
    <td><a href="/t/1000002#reply3" class="count_livid">3</a></td>
  </tr></table>
</div>
</body></html>
"""


class TestSyntheticEdges:
    def test_zero_reply_has_empty_last_replier(self) -> None:
        topics = parse_tab_page(SYNTHETIC_PAGE, source="tab:jobs")
        zero = next(t for t in topics if t.topic_id == 1000001)
        assert zero.replies == 0
        assert zero.last_replier == ""
        assert zero.author == "user_010"

    def test_replied_topic_parses_last_replier(self) -> None:
        topics = parse_tab_page(SYNTHETIC_PAGE, source="tab:jobs")
        replied = next(t for t in topics if t.topic_id == 1000002)
        assert replied.replies == 3
        assert replied.last_replier == "user_012"

    def test_custom_base_url_used_in_url(self) -> None:
        topics = parse_tab_page(SYNTHETIC_PAGE, source="tab:jobs", base_url="http://httpserver:1234")
        assert topics[0].url == "http://httpserver:1234/t/1000001"

    def test_empty_page_returns_empty(self) -> None:
        assert parse_tab_page("<html></html>", source="tab:jobs") == []

    def test_cell_without_topic_id_is_skipped(self) -> None:
        page = (
            '<html><body><div class="cell item">'
            '<span class="item_title"><a href="/t/abc">no id</a></span>'
            "</div></body></html>"
        )
        assert parse_tab_page(page, source="tab:jobs") == []

    def test_timestamp_parse_failure_falls_back_to_now(self) -> None:
        page = (
            '<html><body><div class="cell item">'
            '<span class="item_title"><a href="/t/55#reply1" id="topic-link-55" class="topic-link">t</a></span>'
            '<span class="topic_info"><span title="not-a-date">x</span></span>'
            "</div></body></html>"
        )
        topics = parse_tab_page(page, source="tab:jobs")
        assert len(topics) == 1
        assert topics[0].created_at.tzinfo == UTC
        # fallback "now" is very recent
        assert (datetime.now(UTC) - topics[0].created_at).total_seconds() < 5
