from progress.config import Config, StorageType
from progress.errors import ConfigException

from .auto import AutoStorage
from .base import Storage
from .combined import CombinedStorage as CombinedStorage
from .db import DBStorage
from .file import FileStorage
from .markpost import MarkpostStorage


def get_storage(*, config: Config) -> Storage:
    storage_type = config.report.storage

    if storage_type == StorageType.DB:
        return DBStorage()

    if storage_type == StorageType.AUTO:
        return AutoStorage(config)

    if storage_type == StorageType.MARKPOST:
        if not config.markpost.enabled or not config.markpost.url:
            raise ConfigException(
                "markpost.enabled=true and markpost.url are required when report.storage=markpost"
            )
        return MarkpostStorage(config.markpost)

    if storage_type == StorageType.FILE:
        return FileStorage("data/reports")

    raise ConfigException(f"Unknown storage type: {storage_type}")
