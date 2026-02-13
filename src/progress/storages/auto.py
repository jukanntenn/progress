import logging
from pathlib import Path

from progress.config import Config
from progress.utils.markpost import MarkpostClient

from .file import FileStorage
from .markpost import MarkpostStorage

logger = logging.getLogger(__name__)


class AutoStorage:
    def __init__(self, config: Config) -> None:
        self._config = config
        self._storage = self._create_storage()

    def _create_storage(self):
        markpost_cfg = getattr(self._config, "markpost", None)
        if markpost_cfg and getattr(markpost_cfg, "url", None):
            client = MarkpostClient(markpost_cfg)
            return MarkpostStorage(client)
        return FileStorage()

    def save(self, title: str, body: str | None, directory: Path) -> str:
        return self._storage.save(title, body, directory)
