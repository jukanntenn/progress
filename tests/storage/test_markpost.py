from unittest.mock import Mock, patch

from progress.storages.markpost import MarkpostStorage


def test_markpost_storage_uploads_and_returns_urls():
    with patch("progress.storages.markpost.MarkpostClient") as client_cls:
        mock_client = client_cls.return_value
        mock_client.upload.return_value = "https://example.com/p/123"

        config = Mock()
        storage = MarkpostStorage(config)
        result = storage.save("Title", ["Body"])

        assert result == ["https://example.com/p/123"]
        mock_client.upload.assert_called_once_with("Body", title="Title")


def test_markpost_storage_handles_multiple_bodies():
    with patch("progress.storages.markpost.MarkpostClient") as client_cls:
        mock_client = client_cls.return_value
        mock_client.upload.side_effect = [
            "https://example.com/p/1",
            "https://example.com/p/2",
        ]

        config = Mock()
        storage = MarkpostStorage(config)
        result = storage.save("Title", ["Body 1", "Body 2"])

        assert result == [
            "https://example.com/p/1",
            "https://example.com/p/2",
        ]
        assert mock_client.upload.call_count == 2


def test_markpost_storage_continues_on_batch_failure():
    with patch("progress.storages.markpost.MarkpostClient") as client_cls:
        mock_client = client_cls.return_value
        mock_client.upload.side_effect = [
            Exception("upload failed"),
            "https://example.com/p/2",
        ]

        config = Mock()
        storage = MarkpostStorage(config)
        result = storage.save("Title", ["Body 1", "Body 2"])

        assert result == ["https://example.com/p/2"]
