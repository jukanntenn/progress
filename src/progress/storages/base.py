from typing import Protocol


class Storage(Protocol):
    def save(self, title: str, body: str | None) -> str: ...

