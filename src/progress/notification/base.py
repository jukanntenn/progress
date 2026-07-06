from __future__ import annotations

from typing import Protocol


class Channel(Protocol):
    async def send(self, payload: str) -> None: ...
