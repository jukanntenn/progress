from typing import Protocol


class Storage(Protocol):
    async def save(self, title: str, bodies: list[str]) -> list[str]: ...
