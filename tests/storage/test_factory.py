from unittest.mock import Mock, patch

from progress.config import StorageType
from progress.storages import get_storage


def test_get_storage_returns_db_storage_for_db():
    config = Mock()
    config.report.storage = StorageType.DB

    with patch("progress.storages.DBStorage") as db_cls:
        storage = get_storage(
            config=config,
            repo_id=1,
            commit_hash="a",
            previous_commit_hash="b",
            commit_count=1,
            markpost_url=None,
        )
        assert storage == db_cls.return_value


def test_get_storage_returns_combined_for_file():
    config = Mock()
    config.report.storage = StorageType.FILE

    with patch("progress.storages.CombinedStorage") as combined_cls:
        with patch("progress.storages.DBStorage") as db_cls:
            with patch("progress.storages.FileStorage") as file_cls:
                storage = get_storage(
                    config=config,
                    repo_id=1,
                    commit_hash="a",
                    previous_commit_hash="b",
                    commit_count=1,
                    markpost_url=None,
                )
                assert storage == combined_cls.return_value
                combined_cls.assert_called_once_with(
                    db_cls.return_value, file_cls.return_value
                )


def test_get_storage_returns_db_storage_when_markpost_url_provided():
    config = Mock()
    config.report.storage = StorageType.AUTO

    with patch("progress.storages.DBStorage") as db_cls:
        storage = get_storage(
            config=config,
            repo_id=1,
            commit_hash="a",
            previous_commit_hash="b",
            commit_count=1,
            markpost_url="https://example.com/p/1",
        )
        assert storage == db_cls.return_value


def test_get_storage_accepts_report_type():
    config = Mock()
    config.report.storage = StorageType.DB

    with patch("progress.storages.DBStorage") as db_cls:
        storage = get_storage(
            config=config,
            report_type="proposal",
            commit_count=5,
        )
        assert storage == db_cls.return_value
        db_cls.assert_called_once()
        call_kwargs = db_cls.call_args.kwargs
        assert call_kwargs["report_type"] == "proposal"


def test_get_storage_defaults_report_type():
    config = Mock()
    config.report.storage = StorageType.DB

    with patch("progress.storages.DBStorage") as db_cls:
        get_storage(
            config=config,
            repo_id=1,
            commit_hash="a",
            previous_commit_hash="b",
            commit_count=1,
            markpost_url=None,
        )
        call_kwargs = db_cls.call_args.kwargs
        assert call_kwargs["report_type"] == "repo_update"
