from unittest.mock import Mock, patch

from progress.storages.db import DBStorage


def test_db_storage_creates_report_and_returns_id():
    mock_report = Mock()
    mock_report.id = 123

    with patch("progress.db.models.Report") as report_model:
        report_model.create.return_value = mock_report

        storage = DBStorage()
        result = storage.save("Title", ["Body 1", "Body 2"])

        assert result == ["123"]
        report_model.create.assert_called_once_with(
            title="Title", content="Body 1\n\nBody 2", commit_hash=""
        )


def test_db_storage_joins_bodies():
    mock_report = Mock()
    mock_report.id = 456

    with patch("progress.db.models.Report") as report_model:
        report_model.create.return_value = mock_report

        storage = DBStorage()
        storage.save("Title", ["Part A", "Part B", "Part C"])

        call_kwargs = report_model.create.call_args.kwargs
        assert call_kwargs["content"] == "Part A\n\nPart B\n\nPart C"


def test_db_storage_single_body():
    mock_report = Mock()
    mock_report.id = 789

    with patch("progress.db.models.Report") as report_model:
        report_model.create.return_value = mock_report

        storage = DBStorage()
        result = storage.save("Title", ["Only body"])

        assert result == ["789"]
        call_kwargs = report_model.create.call_args.kwargs
        assert call_kwargs["content"] == "Only body"
