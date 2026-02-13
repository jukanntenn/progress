import logging
from pathlib import Path
from time import time

from progress.errors import ProgressException

logger = logging.getLogger(__name__)


class FileStorage:
    def save(self, title: str, body: str | None, directory: Path) -> str:
        content = f"# {title}\n\n{body or ''}"
        path = directory / f"{int(time())}.md"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            raise ProgressException(f"Failed to write report to {path}: {e}") from e

        return str(path.resolve())
