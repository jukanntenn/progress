from progress.storages.base import Storage


def test_storage_protocol():
    class TestStorage:
        def save(self, title: str, bodies: list[str]) -> list[str]:
            return []

    storage: Storage = TestStorage()
    assert hasattr(storage, "save")
