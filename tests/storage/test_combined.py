from unittest.mock import Mock, patch

from progress.storages.combined import CombinedStorage


def test_combined_storage_saves_to_db_then_primary_and_updates_url():
    mock_db = Mock()
    mock_db.report_id = 123
    mock_db.save.return_value = "123"

    mock_primary = Mock()
    mock_primary.save.return_value = "https://example.com/p/123"

    with patch("progress.storages.combined.Report") as report_model:
        storage = CombinedStorage(mock_db, mock_primary)
        result = storage.save("Title", "Body")

        assert result == "https://example.com/p/123"
        mock_db.save.assert_called_once_with("Title", "Body")
        mock_primary.save.assert_called_once_with("Title", "Body")
        report_model.update.assert_called_once()


def test_combined_storage_does_not_update_when_not_url():
    mock_db = Mock()
    mock_db.report_id = 123
    mock_db.save.return_value = "123"

    mock_primary = Mock()
    mock_primary.save.return_value = "/tmp/report.md"

    with patch("progress.storages.combined.Report") as report_model:
        storage = CombinedStorage(mock_db, mock_primary)
        result = storage.save("Title", "Body")

        assert result == "/tmp/report.md"
        report_model.update.assert_not_called()

