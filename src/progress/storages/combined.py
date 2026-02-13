import logging
from pathlib import Path

from .base import Storage
from .db import DBStorage

logger = logging.getLogger(__name__)


class CombinedStorage:
    def __init__(self, db: DBStorage, primary: Storage) -> None:
        self._db = db
        self._primary = primary

    @property
    def report_id(self) -> int | None:
        return self._db.report_id

    def save(self, title: str, body: str | None, directory: Path) -> str:
        from progress.db.models import Report

        self._db.save(title, body, directory)
        result = self._primary.save(title, body, directory)

        report_id = self._db.report_id
        if report_id is not None and result.startswith("http"):
            Report.update(markpost_url=result).where(Report.id == report_id).execute()

        return result
