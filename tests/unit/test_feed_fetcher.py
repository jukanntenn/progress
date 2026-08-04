"""Unit tests for the feed integration config + fetcher helpers (spec feed).

Covers the pure-function layer (spec 15 unit layer): config schema validation
and the dedup/group/truncate algorithm in
:mod:`progress.integrations.feed.fetcher`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import SecretStr, ValidationError
import pytest

from progress.integrations.feed.client import RawEntry
from progress.integrations.feed.config import FeedIntegrationConfig
from progress.integrations.feed.fetcher import (
    MAX_ENTRIES_PER_FEED,
    Feed,
    filter_new_entries,
    first_entry_meta,
    format_published_at,
    max_entry_id,
)


def _entry(
    entry_id: int, feed_id: int = 1, *, title: str | None = None, feed_title: str = "F", site_url: str = ""
) -> RawEntry:
    return RawEntry(
        id=entry_id,
        feed_id=feed_id,
        title=title or f"e{entry_id}",
        url=f"https://example.com/{entry_id}",
        published_at=datetime(2026, 1, 1, tzinfo=UTC),
        content="content",
        feed={"id": feed_id, "title": feed_title, "site_url": site_url},
    )


class TestFeedConfig:
    def test_zero_config_defaults_to_empty(self) -> None:
        cfg = FeedIntegrationConfig()
        assert cfg.base_url == ""
        assert cfg.api_key.get_secret_value() == ""

    def test_base_url_and_api_key_round_trip(self) -> None:
        cfg = FeedIntegrationConfig(base_url="https://miniflux.example.org", api_key=SecretStr("MF-xxx"))
        assert cfg.base_url == "https://miniflux.example.org"
        assert cfg.api_key.get_secret_value() == "MF-xxx"

    def test_api_key_is_secretstr(self) -> None:
        cfg = FeedIntegrationConfig(api_key=SecretStr("MF-xxx"))
        assert isinstance(cfg.api_key, SecretStr)
        assert "MF-xxx" not in cfg.model_dump_json()

    def test_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FeedIntegrationConfig.model_validate({"base_url": "x", "bogus": "field"})


class TestFilterNewEntries:
    def test_empty_input(self) -> None:
        assert filter_new_entries([], water_marks={}) == {}

    def test_first_time_sees_all(self) -> None:
        entries = [_entry(1), _entry(3), _entry(2)]
        grouped = filter_new_entries(entries, water_marks={1: None})
        assert grouped == {1: [_entry(3), _entry(2), _entry(1)]}

    def test_water_mark_filters_lower_ids(self) -> None:
        entries = [_entry(1), _entry(2), _entry(3), _entry(4)]
        grouped = filter_new_entries(entries, water_marks={1: 2})
        assert grouped == {1: [_entry(4), _entry(3)]}

    def test_water_mark_none_keeps_all(self) -> None:
        entries = [_entry(1), _entry(2)]
        grouped = filter_new_entries(entries, water_marks={1: None})
        assert grouped == {1: [_entry(2), _entry(1)]}

    def test_no_new_entries_returns_empty_list_for_feed(self) -> None:
        entries = [_entry(1), _entry(2)]
        grouped = filter_new_entries(entries, water_marks={1: 5})
        assert grouped == {1: []}

    def test_groups_by_feed(self) -> None:
        entries = [_entry(1, feed_id=10), _entry(2, feed_id=20), _entry(3, feed_id=10)]
        grouped = filter_new_entries(entries, water_marks={})
        assert sorted(grouped.keys()) == [10, 20]
        assert grouped[10] == [_entry(3, feed_id=10), _entry(1, feed_id=10)]
        assert grouped[20] == [_entry(2, feed_id=20)]

    def test_truncates_to_max_entries_per_feed_newest_first(self) -> None:
        entries = [_entry(i) for i in range(1, MAX_ENTRIES_PER_FEED + 5)]
        grouped = filter_new_entries(entries, water_marks={1: None})
        assert len(grouped[1]) == MAX_ENTRIES_PER_FEED
        assert grouped[1][0].id == MAX_ENTRIES_PER_FEED + 4
        assert grouped[1][-1].id == 5

    def test_max_entries_per_feed_is_50(self) -> None:
        assert MAX_ENTRIES_PER_FEED == 50


class TestMaxEntryId:
    def test_empty(self) -> None:
        assert max_entry_id([]) is None

    def test_single(self) -> None:
        assert max_entry_id([_entry(7)]) == 7

    def test_max_of_many(self) -> None:
        assert max_entry_id([_entry(1), _entry(9), _entry(3)]) == 9


class TestFirstEntryMeta:
    def test_returns_feed_id_title_site_url(self) -> None:
        entries = [_entry(1, feed_title="My Feed", site_url="https://feed.example")]
        feed_id, title, site_url = first_entry_meta(entries, fallback_title="x")
        assert feed_id == 1
        assert title == "My Feed"
        assert site_url == "https://feed.example"

    def test_falls_back_when_title_missing(self) -> None:
        entries = [
            RawEntry(
                id=1,
                feed_id=5,
                title="t",
                url="u",
                published_at=datetime(2026, 1, 1, tzinfo=UTC),
                content="c",
                feed={},
            )
        ]
        _, title, site_url = first_entry_meta(entries, fallback_title="fallback")
        assert title == "fallback"
        assert site_url == ""

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            first_entry_meta([], fallback_title="x")


class TestFormatPublishedAt:
    def test_formats_iso_like(self) -> None:
        dt = datetime(2026, 7, 25, 10, 0, 0, tzinfo=UTC)
        assert format_published_at(dt) == "2026-07-25 10:00:00"


class TestFeed:
    def test_entry_count(self) -> None:
        feed = Feed(feed_id=1, title="t", site_url="", entries=[_entry(1), _entry(2)])
        assert feed.entry_count == 2

    def test_default_empty_entries(self) -> None:
        feed = Feed(feed_id=1, title="t", site_url="")
        assert feed.entries == []
        assert feed.entry_count == 0
