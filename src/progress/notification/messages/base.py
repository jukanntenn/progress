from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..base import Channel

logger = logging.getLogger(__name__)


class Message(ABC):
    def __init__(self, channel: Channel) -> None:
        self._channel = channel

    @abstractmethod
    def get_channel(self) -> Channel: ...

    @abstractmethod
    def get_payload(self) -> str: ...

    def send(self, fail_silently: bool = True) -> bool:
        try:
            self.get_channel().send(self.get_payload())
            return True
        except Exception as e:
            logger.warning("Channel failed: %s", e)
            if not fail_silently:
                raise
            return False
