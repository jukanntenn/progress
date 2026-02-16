from progress.config import Config, StorageType
from progress.errors import ConfigException
from progress.utils.markpost import MarkpostClient

from .auto import AutoStorage
from .base import Storage
from .combined import CombinedStorage
from .db import DBStorage
from .file import FileStorage
from .markpost import MarkpostStorage


def get_storage(
    *,
    config: Config,
    report_type: str = "repo_update",
    repo_id: int | None = None,
    commit_hash: str = "",
    previous_commit_hash: str | None = None,
    commit_count: int = 0,
    markpost_url: str | None = None,
) -> Storage:
    storage_type = config.report.storage

    db_storage = DBStorage(
        report_type=report_type,
        repo_id=repo_id,
        commit_hash=commit_hash,
        previous_commit_hash=previous_commit_hash,
        commit_count=commit_count,
        markpost_url=markpost_url,
    )

    if storage_type == StorageType.DB:
        return db_storage

    if storage_type == StorageType.FILE:
        return CombinedStorage(db_storage, FileStorage())

    if storage_type == StorageType.MARKPOST:
        if markpost_url is not None:
            return db_storage
        if not getattr(config.markpost, "enabled", False) or not getattr(
            config.markpost, "url", None
        ):
            raise ConfigException(
                "markpost.enabled=true and markpost.url are required when report.storage=markpost"
            )
        return CombinedStorage(
            db_storage,
            MarkpostStorage(MarkpostClient(config.markpost)),
        )

    if storage_type == StorageType.AUTO:
        if markpost_url is not None:
            return db_storage
        return CombinedStorage(db_storage, AutoStorage(config))

    raise ConfigException(f"Unknown report storage type: {storage_type}")
