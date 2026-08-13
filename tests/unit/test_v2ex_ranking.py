"""Unit tests for v2ex global top-K ranking (spec v2ex §7)."""

from __future__ import annotations

from datetime import UTC, datetime

from progress.integrations.v2ex.fetcher import ClassifiedPost, select_top_k
from progress.integrations.v2ex.parser import RawTopic


def _post(topic_id: int, *, score: int, interested: bool = True, replies: int = 0) -> ClassifiedPost:
    return ClassifiedPost(
        topic=RawTopic(
            topic_id=topic_id,
            title=f"t{topic_id}",
            node_slug="jobs",
            node_name="酷工作",
            author="user",
            created_at=datetime(2026, 8, 12, tzinfo=UTC),
            replies=replies,
            last_replier="",
            url=f"https://www.v2ex.com/t/{topic_id}",
            source="tab:jobs",
        ),
        interested=interested,
        score=score,
        reason="r",
        takeaway="",
    )


class TestSelectTopK:
    def test_only_interested_selected(self) -> None:
        items = [_post(1, score=9, interested=True), _post(2, score=10, interested=False)]
        kept = select_top_k(items, k=5)
        assert [p.topic.topic_id for p in kept] == [1]

    def test_sorted_by_score_desc(self) -> None:
        items = [_post(1, score=5), _post(2, score=9), _post(3, score=7)]
        kept = select_top_k(items, k=5)
        assert [p.topic.topic_id for p in kept] == [2, 3, 1]

    def test_k_caps_results(self) -> None:
        items = [_post(i, score=i) for i in range(1, 6)]
        kept = select_top_k(items, k=2)
        assert [p.topic.topic_id for p in kept] == [5, 4]

    def test_tiebreak_by_replies_then_topic_id(self) -> None:
        items = [
            _post(10, score=8, replies=2),
            _post(20, score=8, replies=5),
            _post(30, score=8, replies=5),
        ]
        kept = select_top_k(items, k=3)
        # same score → more replies first (20,30 over 10); same replies → higher id first (30 over 20)
        assert [p.topic.topic_id for p in kept] == [30, 20, 10]

    def test_empty_input(self) -> None:
        assert select_top_k([], k=5) == []

    def test_zero_k_returns_empty(self) -> None:
        assert select_top_k([_post(1, score=9)], k=0) == []
