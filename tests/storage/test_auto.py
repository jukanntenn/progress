from unittest.mock import AsyncMock, Mock, patch

from progress.storages.auto import AutoStorage


async def test_auto_storage_uses_markpost_when_configured():
    mock_config = Mock()
    mock_config.markpost.enabled = True
    mock_config.markpost.url = "https://markpost.example.com/p/test"

    with patch("progress.storages.auto.MarkpostStorage") as storage_cls:
        storage_cls.return_value.save = AsyncMock(return_value=["url"])
        auto = AutoStorage(mock_config)
        await auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with(mock_config.markpost)


async def test_auto_storage_falls_back_to_file_when_markpost_disabled():
    mock_config = Mock()
    mock_config.markpost.enabled = False
    mock_config.markpost.url = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        storage_cls.return_value.save = AsyncMock(return_value=["path"])
        auto = AutoStorage(mock_config)
        await auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with("data/reports")


async def test_auto_storage_falls_back_to_file_when_no_url():
    mock_config = Mock()
    mock_config.markpost.enabled = True
    mock_config.markpost.url = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        storage_cls.return_value.save = AsyncMock(return_value=["path"])
        auto = AutoStorage(mock_config)
        await auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with("data/reports")
