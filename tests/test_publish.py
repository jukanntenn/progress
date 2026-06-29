"""Tests for the MarkPost publish helper (batching, stubs, Report/Batch rules)."""

from unittest.mock import MagicMock

import pytest

from progress.db import close_db, create_tables, init_db
from progress.db.models import Batch, Report
from progress.publish import (
    PublishResult,
    build_oversize_stub,
    build_report_url,
    byte_size,
    publish_monolithic,
    publish_report,
)


@pytest.fixture()
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    init_db(str(db_path))
    create_tables()
    try:
        yield str(db_path)
    finally:
        close_db()


@pytest.fixture()
def report_row(temp_db):
    return Report.create(
        title="T", commit_hash="h", content="full body", markpost_url=""
    )


def make_client(urls, fail_indices=()):
    """Fake MarkpostClient whose upload returns ``urls`` in order.

    Calls whose index is in ``fail_indices`` raise instead. The list of titles
    passed to each upload is recorded on ``client._titles``.
    """
    client = MagicMock()
    state = {"n": 0, "titles": []}

    def upload(body, title=None):
        idx = state["n"]
        state["n"] += 1
        state["titles"].append(title)
        if idx in fail_indices:
            raise RuntimeError("boom")
        return urls[idx]

    client.upload.side_effect = upload
    client._titles = state["titles"]
    return client


# --------------------------------------------------------------------------- #
# pure helpers
# --------------------------------------------------------------------------- #


def test_byte_size_is_utf8_byte_length():
    assert byte_size("abc") == 3
    assert byte_size("é") == 2
    assert byte_size("中文") == 6


def test_build_report_url_strips_trailing_slash():
    assert build_report_url("https://x.example/", 42) == "https://x.example/report/42"
    assert build_report_url("https://x.example", 1) == "https://x.example/report/1"


def test_build_oversize_stub_none_without_base_url():
    assert build_oversize_stub(None, 1) is None
    assert build_oversize_stub("", 1) is None


def test_build_oversize_stub_contains_webui_link():
    stub = build_oversize_stub("https://x.example", 7)
    assert stub is not None
    assert "https://x.example/report/7" in stub


# --------------------------------------------------------------------------- #
# publish_report
# --------------------------------------------------------------------------- #


def test_publish_report_single_body_sets_url_no_batch_rows(report_row):
    client = make_client(["https://mp/p/1"])

    result = publish_report(
        report_id=report_row.id, title="T", bodies=["body"], markpost_client=client
    )

    assert isinstance(result, PublishResult)
    assert result.batch_urls == ["https://mp/p/1"]
    assert result.markpost_url == "https://mp/p/1"
    assert Report.get_by_id(report_row.id).markpost_url == "https://mp/p/1"
    assert Batch.select().where(Batch.report == report_row.id).count() == 0
    assert client._titles == ["T"]  # no "(n/m)" suffix for a single batch


def test_publish_report_multiple_bodies_clears_url_and_creates_batch_rows(report_row):
    client = make_client(["https://mp/p/1", "https://mp/p/2"])

    result = publish_report(
        report_id=report_row.id, title="T", bodies=["a", "b"], markpost_client=client
    )

    assert result.markpost_url == ""
    assert result.batch_urls == ["https://mp/p/1", "https://mp/p/2"]
    assert Report.get_by_id(report_row.id).markpost_url == ""

    batches = list(
        Batch.select().where(Batch.report == report_row.id).order_by(Batch.seq)
    )
    assert [b.seq for b in batches] == [1, 2]
    assert [b.markpost_url for b in batches] == ["https://mp/p/1", "https://mp/p/2"]
    # Clean title (no suffix) in the DB; suffix only in the uploaded post titles.
    assert all(b.title == "T" for b in batches)
    assert client._titles == ["T (1/2)", "T (2/2)"]


def test_publish_report_partial_failure_only_persists_successful(report_row):
    client = make_client(
        ["https://mp/p/1", "https://mp/p/2", "https://mp/p/3"], fail_indices=(1,)
    )

    result = publish_report(
        report_id=report_row.id,
        title="T",
        bodies=["a", "b", "c"],
        markpost_client=client,
    )

    assert result.batch_urls == ["https://mp/p/1", "https://mp/p/3"]
    assert result.markpost_url == ""  # multi-batch rule still applies
    batches = list(
        Batch.select().where(Batch.report == report_row.id).order_by(Batch.seq)
    )
    assert [b.markpost_url for b in batches] == ["https://mp/p/1", "https://mp/p/3"]


def test_publish_report_all_fail_leaves_empty_url(report_row):
    client = make_client(["https://mp/p/1", "https://mp/p/2"], fail_indices=(0, 1))

    result = publish_report(
        report_id=report_row.id, title="T", bodies=["a", "b"], markpost_client=client
    )

    assert result.batch_urls == []
    assert result.markpost_url == ""
    assert Report.get_by_id(report_row.id).markpost_url == ""
    assert Batch.select().where(Batch.report == report_row.id).count() == 0


def test_publish_report_disabled_client_is_noop(report_row):
    result = publish_report(
        report_id=report_row.id, title="T", bodies=["a"], markpost_client=None
    )
    assert result.markpost_url == ""
    assert result.batch_urls == []


def test_publish_report_empty_bodies_is_noop(report_row):
    client = make_client([])
    result = publish_report(
        report_id=report_row.id, title="T", bodies=[], markpost_client=client
    )
    assert result.batch_urls == []
    client.upload.assert_not_called()


# --------------------------------------------------------------------------- #
# publish_monolithic
# --------------------------------------------------------------------------- #


def test_publish_monolithic_uploads_full_body_when_under_limit(report_row):
    client = make_client(["https://mp/p/full"])

    url = publish_monolithic(
        report_id=report_row.id,
        title="T",
        body="small",
        web_base_url="https://x.example",
        max_batch_size=1000,
        markpost_client=client,
    )

    assert url == "https://mp/p/full"
    assert Report.get_by_id(report_row.id).markpost_url == "https://mp/p/full"
    # Full body uploaded, and the DB content is untouched.
    assert client.upload.call_args.args[0] == "small"
    assert Report.get_by_id(report_row.id).content == "full body"


def test_publish_monolithic_stubs_when_over_limit_with_base_url(report_row):
    big = "x" * 100
    client = make_client(["https://mp/p/stub"])

    url = publish_monolithic(
        report_id=report_row.id,
        title="T",
        body=big,
        web_base_url="https://x.example",
        max_batch_size=10,
        markpost_client=client,
    )

    assert url == "https://mp/p/stub"
    uploaded = client.upload.call_args.args[0]
    assert f"https://x.example/report/{report_row.id}" in uploaded
    assert big not in uploaded  # the oversized body itself was not uploaded


def test_publish_monolithic_skips_when_over_limit_without_base_url(report_row):
    client = make_client(["https://mp/p/stub"])

    url = publish_monolithic(
        report_id=report_row.id,
        title="T",
        body="x" * 100,
        web_base_url=None,
        max_batch_size=10,
        markpost_client=client,
    )

    assert url == ""
    client.upload.assert_not_called()
    assert Report.get_by_id(report_row.id).markpost_url == ""


def test_publish_monolithic_disabled_client_returns_empty(report_row):
    url = publish_monolithic(
        report_id=report_row.id,
        title="T",
        body="small",
        web_base_url="https://x.example",
        max_batch_size=1000,
        markpost_client=None,
    )
    assert url == ""
