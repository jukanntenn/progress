from __future__ import annotations

import json
import logging

import requests

from ...errors import ExternalServiceException

logger = logging.getLogger(__name__)


class FeishuChannel:
    def __init__(self, webhook_url: str, timeout: int = 30) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout

    def send(self, payload: str) -> None:
        try:
            payload_data = json.loads(payload)
            response = requests.post(
                url=self._webhook_url,
                json=payload_data,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except (json.JSONDecodeError, requests.RequestException) as e:
            logger.warning("Failed to send Feishu notification: %s", e)
            raise ExternalServiceException(f"Feishu notification failed: {e}") from e
