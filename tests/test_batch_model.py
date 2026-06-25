"""Tests for the Batch model."""

import pytest

from progress.db import close_db, create_tables, init_db
from progress.db.models import Batch, Report

try:
    from peewee import IntegrityError
except ImportError:  # pragma: no cover
    IntegrityError = Exception


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
def aggregated_report(temp_db):
    return Report.create(
        title="Aggregated Report",
        commit_hash="aggcommit",
        commit_count=10,
        markpost_url="https://markpost.example.com/p-first",
    )


class TestBatchModel:
    def test_create_batch_with_all_fields(self, aggregated_report):
        batch = Batch.create(
            report=aggregated_report.id,
            title="Aggregated Report (1/2)",
            markpost_url="https://markpost.example.com/p-abc",
            seq=1,
        )

        assert batch.id is not None
        assert batch.report_id == aggregated_report.id
        assert batch.title == "Aggregated Report (1/2)"
        assert batch.markpost_url == "https://markpost.example.com/p-abc"
        assert batch.seq == 1

    def test_markpost_url_defaults_to_empty(self, aggregated_report):
        batch = Batch.create(
            report=aggregated_report.id,
            title="Batch 1",
            seq=1,
        )

        assert batch.markpost_url == ""

    def test_report_seq_unique_together(self, aggregated_report):
        Batch.create(
            report=aggregated_report.id,
            title="Batch 1",
            markpost_url="https://markpost.example.com/p-1",
            seq=1,
        )

        with pytest.raises(IntegrityError):
            Batch.create(
                report=aggregated_report.id,
                title="Duplicate",
                markpost_url="https://markpost.example.com/p-2",
                seq=1,
            )

    def test_same_seq_allowed_for_different_reports(self, temp_db):
        report_a = Report.create(title="A", commit_hash="a", commit_count=1)
        report_b = Report.create(title="B", commit_hash="b", commit_count=1)

        batch_a = Batch.create(report=report_a.id, title="A1", seq=1)
        batch_b = Batch.create(report=report_b.id, title="B1", seq=1)

        assert batch_a.id != batch_b.id

    def test_cascade_delete_when_report_deleted(self, aggregated_report):
        for seq in (1, 2):
            Batch.create(
                report=aggregated_report.id,
                title=f"Batch {seq}",
                markpost_url=f"https://markpost.example.com/p-{seq}",
                seq=seq,
            )

        assert Batch.select().where(Batch.report == aggregated_report.id).count() == 2

        aggregated_report.delete_instance()

        assert Batch.select().where(Batch.report == aggregated_report.id).count() == 0

    def test_batches_ordered_by_seq(self, aggregated_report):
        Batch.create(report=aggregated_report.id, title="Second", seq=2)
        Batch.create(report=aggregated_report.id, title="First", seq=1)

        batches = list(
            Batch.select()
            .where(Batch.report == aggregated_report.id)
            .order_by(Batch.seq)
        )

        assert [b.seq for b in batches] == [1, 2]
        assert [b.title for b in batches] == ["First", "Second"]
