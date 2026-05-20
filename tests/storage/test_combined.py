from unittest.mock import Mock, patch

from progress.storages.combined import CombinedStorage


def test_combined_storage_saves_to_db_then_primary():
    mock_primary = Mock()
    mock_primary.save.return_value = ["/tmp/report.md"]

    with patch("progress.storages.combined.DBStorage") as db_cls:
        mock_db = db_cls.return_value
        mock_db.save.return_value = ["123"]

        storage = CombinedStorage(mock_primary)
        result = storage.save("Title", ["Body"])

        assert result == ["/tmp/report.md"]
        mock_db.save.assert_called_once_with("Title", ["Body"])
        mock_primary.save.assert_called_once_with("Title", ["Body"])


def test_combined_storage_returns_primary_result():
    mock_primary = Mock()
    mock_primary.save.return_value = ["https://example.com/p/123"]

    with patch("progress.storages.combined.DBStorage"):
        storage = CombinedStorage(mock_primary)
        result = storage.save("Title", ["Body"])

        assert result == ["https://example.com/p/123"]
