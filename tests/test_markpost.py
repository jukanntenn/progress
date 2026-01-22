"""Tests for MarkpostClient."""

import pytest
import requests

from progress.config import MarkpostConfig
from progress.errors import ProgressException
from progress.markpost import MarkpostClient


class TestUrlParsing:
    """Test URL parsing methods."""

    @pytest.mark.parametrize(
        "url,expected_base,expected_key",
        [
            ("https://example.com/p/test-key", "https://example.com", "test-key"),
            ("https://markpost.example.com/p/abc123xyz", "https://markpost.example.com", "abc123xyz"),
            ("http://localhost:8080/p/dev-key", "http://localhost:8080", "dev-key"),
        ],
    )
    def test_extract_base_url(self, url, expected_base, expected_key):
        """Test base URL extraction."""
        assert MarkpostClient._extract_base_url(url) == expected_base
        assert MarkpostClient._extract_post_key(url) == expected_key

    def test_extract_invalid_url(self):
        """Test invalid URL raises exception."""
        with pytest.raises(ProgressException, match="Invalid markpost URL"):
            MarkpostClient._extract_base_url("not-a-url")

    def test_extract_missing_path(self):
        """Test URL without path raises exception."""
        with pytest.raises(ProgressException, match="missing path"):
            MarkpostClient._extract_post_key("https://example.com")


class TestUrlMasking:
    """Test URL masking for logging."""

    def test_mask_url(self):
        """Test URL masking function."""
        masked = MarkpostClient._mask_url("https://example.com/p/sensitive-key")
        assert "sensitive-key" not in masked
        assert "***" in masked

    def test_mask_short_key(self):
        """Test masking short keys."""
        masked = MarkpostClient._mask_url("https://example.com/p/ab")
        assert "ab" not in masked or "***" in masked


class TestUpload:
    """Test upload method."""

    def test_upload_success(self, monkeypatch):
        """Test successful upload."""
        class FakeResponse:
            status_code = 200

            def json(self):
                return {"id": "test123"}

            def raise_for_status(self):
                pass

        def fake_post(url, json, timeout):
            return FakeResponse()

        monkeypatch.setattr(requests, "post", fake_post)

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        url = client.upload("content", "title")
        assert url == "https://example.com/test123"

    def test_upload_empty_content(self):
        """Test upload with empty content raises exception."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="Content cannot be empty"):
            client.upload("")

    def test_upload_missing_id_field(self, monkeypatch):
        """Test upload when API response missing 'id' field."""
        class FakeResponse:
            status_code = 200

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        def fake_post(url, json, timeout):
            return FakeResponse()

        monkeypatch.setattr(requests, "post", fake_post)

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="missing 'id'"):
            client.upload("content", "title")

    def test_upload_http_error(self, monkeypatch, caplog):
        """Test upload failure with HTTP error."""
        class FakeResponse:
            status_code = 400
            text = '{"error": "Invalid request"}'

        def fake_post(url, json, timeout):
            e = requests.RequestException()
            e.response = FakeResponse()
            raise e

        monkeypatch.setattr(requests, "post", fake_post)

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="Failed to upload.*status: 400"):
            client.upload("content", "title")


class TestGetStatus:
    """Test get_status method."""

    def test_get_status_exists(self, monkeypatch):
        """Test checking existing post."""
        class FakeResponse:
            status_code = 200

        def fake_get(url, timeout):
            return FakeResponse()

        monkeypatch.setattr(requests, "get", fake_get)

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        assert client.get_status("abc123") is True

    def test_get_status_not_found(self, monkeypatch):
        """Test checking non-existent post."""
        class FakeResponse:
            status_code = 404

        def fake_get(url, timeout):
            return FakeResponse()

        monkeypatch.setattr(requests, "get", fake_get)

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        assert client.get_status("abc123") is False

    def test_get_status_empty_id(self):
        """Test get_status with empty post_id."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="Post ID cannot be empty"):
            client.get_status("")
