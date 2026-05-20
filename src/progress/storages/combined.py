from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .db import DBStorage

if TYPE_CHECKING:
    from .base import Storage

logger = logging.getLogger(__name__)


class CombinedStorage:
    def __init__(self, primary: Storage) -> None:
        self._primary = primary
        self._db = DBStorage()

    def save(self, title: str, bodies: list[str]) -> list[str]:
        logger.debug("Saving to combined storage (primary + database)")
        self._db.save(title, bodies)
        return self._primary.save(title, bodies)
