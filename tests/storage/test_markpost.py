from pathlib import Path
from unittest.mock import Mock

from progress.storages.markpost import MarkpostStorage


def test_markpost_storage_uploads_and_returns_url():
    client = Mock()
    client.upload.return_value = "https://example.com/p/123"

    storage = MarkpostStorage(client)
    result = storage.save("Title", "Body", Path("/reports"))

    assert result == "https://example.com/p/123"
    client.upload.assert_called_once_with("Body", title="Title")


def test_markpost_storage_ignores_directory():
    client = Mock()
    client.upload.return_value = "https://example.com/p/1"
    storage = MarkpostStorage(client)
    result = storage.save("Title", "Body", Path("/ignored"))
    assert result == "https://example.com/p/1"
