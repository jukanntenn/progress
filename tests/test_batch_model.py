"""Tests for the Batch model."""

import pytest
from tortoise.exceptions import IntegrityError

from progress.db import close_db, create_tables, init_db
from progress.db.models import Batch, Report


@pytest.fixture()
async def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    await init_db(str(db_path))
    await create_tables()
    try:
        yield str(db_path)
    finally:
        await close_db()


@pytest.fixture()
async def aggregated_report(temp_db):
    return await Report.create(
        title="Aggregated Report",
        commit_hash="aggcommit",
        commit_count=10,
        markpost_url="https://markpost.example.com/p-first",
    )


class TestBatchModel:
    async def test_create_batch_with_all_fields(self, aggregated_report):
        batch = await Batch.create(
            report_id=aggregated_report.id,
            title="Aggregated Report (1/2)",
            markpost_url="https://markpost.example.com/p-abc",
            seq=1,
        )

        assert batch.id is not None
        assert batch.report_id == aggregated_report.id  # ty: ignore[unresolved-attribute]  # tortoise exposes report_id as the raw FK column; not in the model stubs
        assert batch.title == "Aggregated Report (1/2)"
        assert batch.markpost_url == "https://markpost.example.com/p-abc"
        assert batch.seq == 1

    async def test_markpost_url_defaults_to_empty(self, aggregated_report):
        batch = await Batch.create(
            report_id=aggregated_report.id,
            title="Batch 1",
            seq=1,
        )

        assert batch.markpost_url == ""

    async def test_report_seq_unique_together(self, aggregated_report):
        await Batch.create(
            report_id=aggregated_report.id,
            title="Batch 1",
            markpost_url="https://markpost.example.com/p-1",
            seq=1,
        )

        with pytest.raises(IntegrityError):
            await Batch.create(
                report_id=aggregated_report.id,
                title="Duplicate",
                markpost_url="https://markpost.example.com/p-2",
                seq=1,
            )

    async def test_same_seq_allowed_for_different_reports(self, temp_db):
        report_a = await Report.create(title="A", commit_hash="a", commit_count=1)
        report_b = await Report.create(title="B", commit_hash="b", commit_count=1)

        batch_a = await Batch.create(report_id=report_a.id, title="A1", seq=1)
        batch_b = await Batch.create(report_id=report_b.id, title="B1", seq=1)

        assert batch_a.id != batch_b.id

    async def test_cascade_delete_when_report_deleted(self, aggregated_report):
        for seq in (1, 2):
            await Batch.create(
                report_id=aggregated_report.id,
                title=f"Batch {seq}",
                markpost_url=f"https://markpost.example.com/p-{seq}",
                seq=seq,
            )

        assert await Batch.filter(report_id=aggregated_report.id).count() == 2

        await aggregated_report.delete()

        assert await Batch.filter(report_id=aggregated_report.id).count() == 0

    async def test_batches_ordered_by_seq(self, aggregated_report):
        await Batch.create(report_id=aggregated_report.id, title="Second", seq=2)
        await Batch.create(report_id=aggregated_report.id, title="First", seq=1)

        batches = await Batch.filter(report_id=aggregated_report.id).order_by("seq")

        assert [b.seq for b in batches] == [1, 2]
        assert [b.title for b in batches] == ["First", "Second"]
