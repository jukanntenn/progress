from unittest.mock import Mock

from progress.storages.markpost import MarkpostStorage


def test_markpost_storage_uploads_and_returns_url():
    client = Mock()
    client.upload.return_value = "https://example.com/p/123"

    storage = MarkpostStorage(client)
    result = storage.save("Title", "Body")

    assert result == "https://example.com/p/123"
    client.upload.assert_called_once_with("Body", title="Title")
