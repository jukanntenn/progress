from typing import Protocol


class Storage(Protocol):
    def save(self, title: str, bodies: list[str]) -> list[str]: ...
