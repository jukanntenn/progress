from unittest.mock import AsyncMock, Mock, patch

from progress.storages.combined import CombinedStorage


async def test_combined_storage_saves_to_db_then_primary():
    mock_primary = Mock()
    mock_primary.save = AsyncMock(return_value=["/tmp/report.md"])

    with patch("progress.storages.combined.DBStorage") as db_cls:
        mock_db = db_cls.return_value
        mock_db.save = AsyncMock(return_value=["123"])

        storage = CombinedStorage(mock_primary)
        result = await storage.save("Title", ["Body"])

        assert result == ["/tmp/report.md"]
        mock_db.save.assert_called_once_with("Title", ["Body"])
        mock_primary.save.assert_called_once_with("Title", ["Body"])


async def test_combined_storage_returns_primary_result():
    mock_primary = Mock()
    mock_primary.save = AsyncMock(return_value=["https://example.com/p/123"])

    with patch("progress.storages.combined.DBStorage") as db_cls:
        db_cls.return_value.save = AsyncMock(return_value=["123"])
        storage = CombinedStorage(mock_primary)
        result = await storage.save("Title", ["Body"])

        assert result == ["https://example.com/p/123"]
