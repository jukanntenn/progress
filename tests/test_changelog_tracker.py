from unittest.mock import Mock
from zoneinfo import ZoneInfo

import requests
import pytest

from progress.changelog_tracker import ChangelogTrackerManager
from progress.config import ChangelogTrackerConfig
from progress.db import close_db, create_tables, init_db
from progress.models import ChangelogTracker

@pytest.fixture()
def db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    create_tables()
    yield
    close_db()


def _fake_requests_get_factory(payload_by_url: dict[str, str]):
    class FakeResponse:
        def __init__(self, text: str):
            self.text = text
            self.content = text.encode("utf-8")
            self.encoding = "utf-8"
            self.apparent_encoding = "utf-8"

        def raise_for_status(self):
            return None

    def fake_get(url: str, *args, **kwargs):
        if url not in payload_by_url:
            raise requests.RequestException(f"missing url: {url}")
        return FakeResponse(payload_by_url[url])

    return fake_get


def test_sync_creates_updates_and_deletes_trackers(db):
    cfg = Mock()
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    cfg.changelog_trackers = []

    manager = ChangelogTrackerManager(cfg=cfg)

    trackers = [
        ChangelogTrackerConfig(
            name="A",
            url="https://example.com/a",
            parser_type="markdown_heading",
            enabled=True,
        )
    ]

    result = manager.sync(trackers)
    assert result["created"] == 1
    assert ChangelogTracker.select().count() == 1

    trackers2 = [
        ChangelogTrackerConfig(
            name="A2",
            url="https://example.com/a",
            parser_type="markdown_heading",
            enabled=False,
        )
    ]
    result2 = manager.sync(trackers2)
    assert result2["updated"] == 1

    row = ChangelogTracker.select().where(ChangelogTracker.url == "https://example.com/a").first()
    assert row is not None
    assert row.name == "A2"
    assert row.enabled is False

    result3 = manager.sync([])
    assert result3["deleted"] == 1
    assert ChangelogTracker.select().count() == 0


def test_check_first_time_sends_notification_and_updates_last_seen_version(db, monkeypatch):
    import progress.changelog_parsers as cp

    url = "https://example.com/a"
    monkeypatch.setattr(
        cp.requests,
        "get",
        _fake_requests_get_factory(
            {
                url: """## 1.0.0\nHello\n""",
            }
        ),
    )

    tracker = ChangelogTracker.create(
        name="A",
        url=url,
        parser_type="markdown_heading",
        enabled=True,
    )

    cfg = Mock()
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    cfg.changelog_trackers = []

    manager = ChangelogTrackerManager(cfg=cfg)

    result = manager.check(tracker)
    assert result.status == "success"
    assert [e.version for e in result.new_entries] == ["1.0.0"]

    tracker_db = ChangelogTracker.get_by_id(tracker.id)
    assert tracker_db.last_seen_version == "1.0.0"
    assert tracker_db.last_check_time is not None


def test_check_no_new_version_does_not_notify(db, monkeypatch):
    import progress.changelog_parsers as cp

    url = "https://example.com/a"
    monkeypatch.setattr(
        cp.requests,
        "get",
        _fake_requests_get_factory(
            {
                url: """## 1.0.0\nHello\n""",
            }
        ),
    )

    tracker = ChangelogTracker.create(
        name="A",
        url=url,
        parser_type="markdown_heading",
        enabled=True,
        last_seen_version="1.0.0",
    )

    cfg = Mock()
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    cfg.changelog_trackers = []

    manager = ChangelogTrackerManager(cfg=cfg)

    result = manager.check(tracker)
    assert result.status == "no_new_version"
    assert result.new_entries == []


def test_check_all_runs_in_config_order_and_skips_disabled(db, monkeypatch):
    import progress.changelog_parsers as cp

    url_a = "https://example.com/a"
    url_b = "https://example.com/b"
    url_c = "https://example.com/c"

    monkeypatch.setattr(
        cp.requests,
        "get",
        _fake_requests_get_factory(
            {
                url_a: """## 1.0.0\nA\n""",
                url_b: """## 1.0.0\nB\n""",
                url_c: """## 1.0.0\nC\n""",
            }
        ),
    )

    cfg = Mock()
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    cfg.changelog_trackers = [
        ChangelogTrackerConfig(
            name="A",
            url=url_a,
            parser_type="markdown_heading",
            enabled=True,
        ),
        ChangelogTrackerConfig(
            name="B",
            url=url_b,
            parser_type="markdown_heading",
            enabled=True,
        ),
        ChangelogTrackerConfig(
            name="C",
            url=url_c,
            parser_type="markdown_heading",
            enabled=False,
        ),
    ]

    manager = ChangelogTrackerManager(cfg=cfg)
    manager.sync(cfg.changelog_trackers)

    result = manager.check_all()
    assert [r.name for r in result.results] == ["A", "B", "C"]
    assert [r.latest_version for r in result.results[:2]] == ["1.0.0", "1.0.0"]
    assert [e.version for e in result.results[0].new_entries] == ["1.0.0"]
    assert [e.version for e in result.results[1].new_entries] == ["1.0.0"]
    assert result.results[2].status == "skipped"


def test_check_extracts_multiple_new_versions_until_last_seen(db, monkeypatch):
    import progress.changelog_parsers as cp

    url = "https://example.com/a"
    monkeypatch.setattr(
        cp.requests,
        "get",
        _fake_requests_get_factory(
            {
                url: """## 3.0.0\nA\n\n## 2.0.0\nB\n\n## 1.0.0\nC\n""",
            }
        ),
    )

    tracker = ChangelogTracker.create(
        name="A",
        url=url,
        parser_type="markdown_heading",
        enabled=True,
        last_seen_version="1.0.0",
    )

    cfg = Mock()
    cfg.get_timezone = Mock(return_value=ZoneInfo("UTC"))
    cfg.changelog_trackers = []

    manager = ChangelogTrackerManager(cfg=cfg)
    result = manager.check(tracker)

    assert result.status == "success"
    assert [e.version for e in result.new_entries] == ["3.0.0", "2.0.0"]
    tracker_db = ChangelogTracker.get_by_id(tracker.id)
    assert tracker_db.last_seen_version == "3.0.0"
