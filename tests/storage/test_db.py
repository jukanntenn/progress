from pathlib import Path
from unittest.mock import Mock, patch

from progress.storages.db import DBStorage


def test_db_storage_creates_report_and_returns_id():
    mock_report = Mock()
    mock_report.id = 123

    with patch("progress.db.models.Report") as report_model:
        report_model.create.return_value = mock_report

        storage = DBStorage(
            repo_id=1,
            commit_hash="abc",
            previous_commit_hash="def",
            commit_count=2,
            markpost_url=None,
        )
        result = storage.save("Title", "Body", Path("/reports"))

        assert result == "123"
        assert storage.report_id == 123
        report_model.create.assert_called_once()


def test_db_storage_ignores_directory():
    mock_report = Mock()
    mock_report.id = 456

    with patch("progress.db.models.Report") as report_model:
        report_model.create.return_value = mock_report

        storage = DBStorage(
            repo_id=1,
            commit_hash="abc",
            previous_commit_hash="def",
            commit_count=5,
            markpost_url=None,
        )
        storage.save("Title", "Body", Path("/ignored"))
        report_model.create.assert_called_once()
