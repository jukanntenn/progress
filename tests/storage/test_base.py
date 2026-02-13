from progress.storages.base import Storage


def test_storage_protocol_accepts_save_method():
    class MockStorage:
        def save(self, title: str, body: str | None) -> str:
            return "mock-result"

    storage: Storage = MockStorage()
    assert storage.save("t", "b") == "mock-result"
