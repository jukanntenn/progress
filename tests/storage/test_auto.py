from unittest.mock import Mock, patch

from progress.storages.auto import AutoStorage


def test_auto_storage_uses_markpost_when_configured():
    mock_config = Mock()
    mock_config.markpost.enabled = True
    mock_config.markpost.url = "https://markpost.example.com/p/test"

    with patch("progress.storages.auto.MarkpostStorage") as storage_cls:
        auto = AutoStorage(mock_config)
        auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with(mock_config.markpost)


def test_auto_storage_falls_back_to_file_when_markpost_disabled():
    mock_config = Mock()
    mock_config.markpost.enabled = False
    mock_config.markpost.url = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        auto = AutoStorage(mock_config)
        auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with("data/reports")


def test_auto_storage_falls_back_to_file_when_no_url():
    mock_config = Mock()
    mock_config.markpost.enabled = True
    mock_config.markpost.url = None

    with patch("progress.storages.auto.FileStorage") as storage_cls:
        auto = AutoStorage(mock_config)
        auto.save("Title", ["Body"])
        storage_cls.assert_called_once_with("data/reports")
