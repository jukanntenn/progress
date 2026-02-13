import logging

from progress.utils.markpost import MarkpostClient

logger = logging.getLogger(__name__)


class MarkpostStorage:
    def __init__(self, client: MarkpostClient) -> None:
        self._client = client

    def save(self, title: str, body: str | None) -> str:
        logger.info(f"Uploading report to Markpost: {title}")
        return self._client.upload(body or "", title=title or None)
