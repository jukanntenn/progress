import logging
from pathlib import Path
from time import time_ns

from progress.errors import ProgressException

logger = logging.getLogger(__name__)


class FileStorage:
    def __init__(self, directory: str) -> None:
        self._directory = Path(directory)

    def save(self, title: str, bodies: list[str]) -> list[str]:
        full_body = "\n\n".join(bodies)
        content = f"# {title}\n\n{full_body}"
        path = self._directory / f"{time_ns()}.md"
        logger.debug("Saving report to %s", path)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.error("Failed to write report to %s: %s", path, e)
            raise ProgressException(f"Failed to write report to {path}: {e}") from e

        return [str(path)]
