from pathlib import Path
from unittest.mock import Mock, patch

from progress.storages.auto import AutoStorage


def test_auto_storage_uses_markpost_when_configured():
    mock_config = Mock()
    mock_config.markpost.url = "https://markpost.example.com/p/test"

    with patch("progress.storages.auto.MarkpostClient") as client_cls:
        with patch("progress.storages.auto.MarkpostStorage") as storage_cls:
            auto = AutoStorage(mock_config)
            auto.save("Title", "Body", Path("/reports"))
            client_cls.assert_called_once()
            storage_cls.assert_called_once()


def test_auto_storage_falls_back_to_file_when_markpost_missing():
    mock_config = Mock()
    mock_config.markpost = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        auto = AutoStorage(mock_config)
        auto.save("Title", "Body", Path("/reports"))
        storage_cls.assert_called_once_with()


def test_auto_storage_passes_directory_to_file_storage():
    mock_config = Mock()
    mock_config.markpost = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        auto = AutoStorage(mock_config)
        auto.save("Title", "Body", Path("/custom/dir"))
        storage_cls.return_value.save.assert_called_once_with(
            "Title", "Body", Path("/custom/dir")
        )
