"""Unit tests for v2ex water-mark dedup (spec v2ex §4)."""

from __future__ import annotations

from datetime import UTC, datetime

from progress.integrations.v2ex.fetcher import filter_new_topics, max_topic_id
from progress.integrations.v2ex.parser import RawTopic


def _topic(topic_id: int, *, source: str = "tab:jobs") -> RawTopic:
    return RawTopic(
        topic_id=topic_id,
        title=f"t{topic_id}",
        node_slug="jobs",
        node_name="酷工作",
        author="user",
        created_at=datetime(2026, 8, 12, tzinfo=UTC),
        replies=0,
        last_replier="",
        url=f"https://www.v2ex.com/t/{topic_id}",
        source=source,
    )


class TestFilterNewTopics:
    def test_first_run_keeps_all(self) -> None:
        topics = [_topic(1), _topic(2), _topic(3)]
        assert filter_new_topics(topics, last_topic_id=None) == topics

    def test_keeps_only_above_water_mark(self) -> None:
        topics = [_topic(1), _topic(2), _topic(3), _topic(5)]
        kept = filter_new_topics(topics, last_topic_id=2)
        assert [t.topic_id for t in kept] == [3, 5]

    def test_water_mark_at_max_keeps_none(self) -> None:
        topics = [_topic(1), _topic(2)]
        assert filter_new_topics(topics, last_topic_id=2) == []

    def test_unsorted_page_still_scanned(self) -> None:
        # tab page sorts by last-active, not by id
        topics = [_topic(5), _topic(1), _topic(9), _topic(3)]
        kept = filter_new_topics(topics, last_topic_id=4)
        assert {t.topic_id for t in kept} == {5, 9}


class TestMaxTopicId:
    def test_empty_returns_none(self) -> None:
        assert max_topic_id([]) is None

    def test_returns_highest(self) -> None:
        assert max_topic_id([_topic(3), _topic(7), _topic(2)]) == 7
