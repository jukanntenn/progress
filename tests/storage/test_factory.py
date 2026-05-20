from unittest.mock import Mock, patch

import pytest

from progress.config import StorageType
from progress.errors import ConfigException
from progress.storages import get_storage


def test_get_storage_returns_db_storage_for_db():
    config = Mock()
    config.report.storage = StorageType.DB

    with patch("progress.storages.DBStorage") as db_cls:
        storage = get_storage(config=config)
        assert storage == db_cls.return_value


def test_get_storage_returns_auto_storage_for_auto():
    config = Mock()
    config.report.storage = StorageType.AUTO

    with patch("progress.storages.AutoStorage") as auto_cls:
        storage = get_storage(config=config)
        assert storage == auto_cls.return_value
        auto_cls.assert_called_once_with(config)


def test_get_storage_returns_markpost_storage():
    config = Mock()
    config.report.storage = StorageType.MARKPOST
    config.markpost.enabled = True
    config.markpost.url = "https://example.com/p/test"

    with patch("progress.storages.MarkpostStorage") as markpost_cls:
        storage = get_storage(config=config)
        assert storage == markpost_cls.return_value
        markpost_cls.assert_called_once_with(config.markpost)


def test_get_storage_raises_when_markpost_not_configured():
    config = Mock()
    config.report.storage = StorageType.MARKPOST
    config.markpost.enabled = False
    config.markpost.url = None

    with pytest.raises(
        ConfigException, match="markpost.enabled=true and markpost.url are required"
    ):
        get_storage(config=config)


def test_get_storage_returns_file_storage_for_file():
    config = Mock()
    config.report.storage = StorageType.FILE

    with patch("progress.storages.FileStorage") as file_cls:
        storage = get_storage(config=config)
        assert storage == file_cls.return_value
        file_cls.assert_called_once_with("data/reports")
