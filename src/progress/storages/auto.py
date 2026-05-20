from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from progress.config import Config

from .file import FileStorage
from .markpost import MarkpostStorage

if TYPE_CHECKING:
    from .base import Storage

logger = logging.getLogger(__name__)


class AutoStorage:
    def __init__(self, config: Config) -> None:
        markpost_config = config.markpost
        if markpost_config.enabled and markpost_config.url:
            logger.debug("Using Markpost storage")
            self._storage: Storage = MarkpostStorage(markpost_config)
        else:
            logger.debug("Using file storage")
            self._storage = FileStorage("data/reports")

    def save(self, title: str, bodies: list[str]) -> list[str]:
        return self._storage.save(title, bodies)
