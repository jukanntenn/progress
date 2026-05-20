from __future__ import annotations

import json
import logging

import requests

from ...errors import ExternalServiceException

logger = logging.getLogger(__name__)


class FeishuChannel:
    def __init__(self, webhook_url: str, timeout: int) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout

    def send(self, payload: str) -> None:
        logger.info("Sending Feishu notification")
        card = json.loads(payload)
        payload_data = {"msg_type": "interactive", "card": card}
        try:
            resp = requests.post(
                url=self._webhook_url, json=payload_data, timeout=self._timeout
            )
            resp.raise_for_status()
            logger.info("Feishu notification sent successfully")
        except requests.RequestException as e:
            logger.warning("Failed to send Feishu notification: %s", e)
            raise ExternalServiceException(f"Feishu notification failed: {e}") from e
