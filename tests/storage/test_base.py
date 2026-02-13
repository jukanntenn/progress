from pathlib import Path

from progress.storages.base import Storage


def test_storage_protocol_requires_directory():
    class TestStorage:
        def save(self, title: str, body: str | None, directory: Path) -> str:
            return ""

    storage: Storage = TestStorage()
    assert hasattr(storage, "save")
