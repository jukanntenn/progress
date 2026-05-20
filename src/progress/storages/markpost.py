from __future__ import annotations

import logging

from progress.config import MarkpostConfig
from progress.utils.markpost import MarkpostClient

logger = logging.getLogger(__name__)


class MarkpostStorage:
    def __init__(self, config: MarkpostConfig) -> None:
        self._client = MarkpostClient(config)

    def save(self, title: str, bodies: list[str]) -> list[str]:
        urls: list[str] = []
        total = len(bodies)
        for idx, body in enumerate(bodies):
            try:
                url = self._client.upload(body, title=title)
                urls.append(url)
            except Exception:
                logger.warning(
                    "Batch %d/%d upload failed, continuing with remaining batches",
                    idx + 1,
                    total,
                )
        return urls
