"""Tests for save_report ensuring no duplicate markpost uploads."""

from unittest.mock import MagicMock, patch

import pytest

from progress.db import close_db, create_tables, init_db, save_report
from progress.db.models import Report, Repository


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
def sample_repo(temp_db):
    repo = Repository.create(
        name="test/repo",
        url="https://github.com/test/repo.git",
        branch="main",
    )
    return repo


class TestSaveReportNoStorageUpload:
    """save_report must only persist to the database — never upload to external storage."""

    def test_does_not_call_storage_save(self, temp_db):
        mock_config = MagicMock()
        mock_config.report.storage = "auto"

        with patch("progress.storages.get_storage") as mock_get_storage:
            mock_storage = MagicMock()
            mock_storage.save.return_value = ["https://example.com/p/abc"]
            mock_get_storage.return_value = mock_storage

            save_report(
                config=mock_config,
                content="some content",
                title="Test",
            )

            mock_get_storage.assert_not_called()
            mock_storage.save.assert_not_called()

    def test_does_not_call_storage_even_with_content_and_config(self, temp_db):
        mock_config = MagicMock()
        mock_config.report.storage = "markpost"

        with patch("progress.storages.get_storage") as mock_get_storage:
            save_report(
                config=mock_config,
                content="detailed report body",
                title="Important Report",
                commit_count=5,
            )

            mock_get_storage.assert_not_called()

    def test_stores_markpost_url_from_caller(self, temp_db, sample_repo):
        url = "https://markpost.example.com/p-abc123"
        report_id = save_report(
            config=None,
            repo_id=sample_repo.id,
            commit_hash="abc123",
            content="report body",
            markpost_url=url,
        )

        report = Report.get_by_id(report_id)
        assert report.markpost_url == url

    def test_empty_markpost_url_when_not_provided(self, temp_db, sample_repo):
        report_id = save_report(
            repo_id=sample_repo.id,
            commit_hash="def456",
            content="report body",
        )

        report = Report.get_by_id(report_id)
        assert report.markpost_url == ""

    def test_saves_all_fields_correctly(self, temp_db, sample_repo):
        report_id = save_report(
            config=None,
            repo_id=sample_repo.id,
            commit_hash="aaa111",
            previous_commit_hash="bbb222",
            commit_count=7,
            content="full content",
            title="My Title",
            report_type="changelog",
        )

        report = Report.get_by_id(report_id)
        assert report.repo_id == sample_repo.id
        assert report.commit_hash == "aaa111"
        assert report.previous_commit_hash == "bbb222"
        assert report.commit_count == 7
        assert report.content == "full content"
        assert report.title == "My Title"
        assert report.report_type == "changelog"


class TestNoDuplicateUploadsInBatchFlow:
    """Simulate the batch processing flow to ensure only one markpost upload."""

    def test_batch_flow_single_upload(self, temp_db, sample_repo):
        """Replicate the batch processing flow: batch upload + individual saves + aggregated save.

        Only the batch upload via markpost_client should produce an HTTP call.
        The individual report saves and aggregated report save must NOT trigger
        additional uploads.
        """
        mock_config = MagicMock()
        mock_config.report.storage = "auto"

        with (
            patch("progress.storages.get_storage") as mock_get_storage,
            patch("progress.utils.markpost.MarkpostClient") as mock_client_cls,
        ):
            mock_storage = MagicMock()
            mock_storage.save.return_value = ["https://example.com/p/dup"]
            mock_get_storage.return_value = mock_storage

            mock_client = mock_client_cls.return_value
            mock_client.upload_batch.return_value = "https://example.com/p/batch1"
            batch_url = mock_client.upload_batch("aggregated content", "Batch Title")

            save_report(
                config=mock_config,
                repo_id=sample_repo.id,
                commit_hash="c1",
                content="individual report 1",
            )
            save_report(
                config=mock_config,
                repo_id=sample_repo.id,
                commit_hash="c2",
                content="individual report 2",
            )
            save_report(
                config=mock_config,
                content="full aggregated report",
                title="Batch Title",
                markpost_url=batch_url,
                commit_count=10,
            )

            assert mock_client.upload_batch.call_count == 1
            mock_get_storage.assert_not_called()
            mock_storage.save.assert_not_called()

            reports = list(Report.select().order_by(Report.id))
            assert len(reports) == 3

            agg_report = [r for r in reports if r.title == "Batch Title"][0]
            assert agg_report.markpost_url == "https://example.com/p/batch1"

    def test_batch_flow_no_markpost_client_still_no_storage_calls(
        self, temp_db, sample_repo
    ):
        """When markpost_client is None (disabled), save_report must still not upload."""
        mock_config = MagicMock()
        mock_config.report.storage = "auto"

        with patch("progress.storages.get_storage") as mock_get_storage:
            save_report(
                config=mock_config,
                repo_id=sample_repo.id,
                commit_hash="c1",
                content="report",
            )

            mock_get_storage.assert_not_called()

    def test_aggregated_report_preserves_batch_url(self, temp_db):
        batch_url = "https://markpost.example.com/p-xyz789"
        report_id = save_report(
            config=None,
            content="aggregated content",
            title="Unified Title",
            markpost_url=batch_url,
            commit_count=3,
        )

        report = Report.get_by_id(report_id)
        assert report.markpost_url == batch_url
        assert report.content == "aggregated content"


class TestPreviousBugScenario:
    """Regression tests that reproduce the exact bug from the logs.

    Before the fix, save_report() would call storage.save() when:
      - config was not None
      - content was truthy
      - config.report.storage was not 'db'

    This caused:
      - Individual reports to attempt markpost uploads (failed with 400)
      - Aggregated report to upload again (duplicate of batch upload)
    """

    def test_individual_report_save_does_not_trigger_upload(self, temp_db, sample_repo):
        mock_config = MagicMock()
        mock_config.report.storage = "auto"

        with patch("progress.storages.get_storage") as mock_get_storage:
            report_id = save_report(
                config=mock_config,
                repo_id=sample_repo.id,
                commit_hash="deadbeef",
                previous_commit_hash="cafebabe",
                commit_count=1,
                content="# Report\n\nSome content",
            )

            mock_get_storage.assert_not_called()
            report = Report.get_by_id(report_id)
            assert report.markpost_url == ""

    def test_aggregated_save_with_url_does_not_reupload(self, temp_db):
        mock_config = MagicMock()
        mock_config.report.storage = "auto"
        existing_url = "https://markpost.bytehome.fun/p-IiY6V-fGrLBbAf8VazecF"

        with patch("progress.storages.get_storage") as mock_get_storage:
            report_id = save_report(
                config=mock_config,
                content="aggregated report body",
                title="Weekly Report",
                markpost_url=existing_url,
                commit_count=5,
            )

            mock_get_storage.assert_not_called()
            report = Report.get_by_id(report_id)
            assert report.markpost_url == existing_url

    def test_full_run_no_duplicate_uploads(self, temp_db, sample_repo):
        """Simulate a full run matching the log pattern:
        - 1 batch upload (succeeds)
        - N individual report saves
        - 1 aggregated report save
        Total markpost HTTP calls should be exactly 1.
        """
        mock_config = MagicMock()
        mock_config.report.storage = "auto"
        upload_calls = []

        def track_upload(content, title, **kwargs):
            upload_calls.append({"title": title, "content_len": len(content)})
            return "https://markpost.example.com/p-new"

        with (
            patch("progress.storages.get_storage") as mock_get_storage,
            patch("progress.utils.markpost.MarkpostClient") as mock_client_cls,
        ):
            mock_client = mock_client_cls.return_value
            mock_client.upload_batch.side_effect = track_upload

            batch_url = mock_client.upload_batch("batch content", "Run Title")

            for i in range(5):
                save_report(
                    config=mock_config,
                    repo_id=sample_repo.id,
                    commit_hash=f"commit{i}",
                    content=f"report content {i}",
                )

            save_report(
                config=mock_config,
                content="full aggregated report",
                title="Run Title",
                markpost_url=batch_url,
                commit_count=5,
            )

            assert len(upload_calls) == 1, (
                f"Expected exactly 1 markpost upload, got {len(upload_calls)}"
            )
            mock_get_storage.assert_not_called()

            all_reports = list(Report.select())
            individual_reports = [r for r in all_reports if r.repo_id == sample_repo.id]
            agg_reports = [r for r in all_reports if r.repo_id is None]

            assert len(individual_reports) == 5
            assert len(agg_reports) == 1
            assert agg_reports[0].markpost_url == batch_url
