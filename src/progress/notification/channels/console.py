from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class ConsoleChannel:
    async def send(self, payload: str) -> None:
        logger.debug("Sending console notification")
        print(payload)
