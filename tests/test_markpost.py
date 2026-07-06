"""Tests for MarkpostClient."""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from progress.config import MarkpostConfig
from progress.errors import ClientError, ProgressException
from progress.utils.markpost import MarkpostClient


def _client_response_error(status: int, message: str) -> aiohttp.ClientResponseError:
    """Build a ClientResponseError whose __str__ won't blow up (needs real_url)."""
    request_info = MagicMock()
    request_info.real_url = "https://example.com/p/key"
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=status,
        message=message,
    )


class TestUrlParsing:
    """Test URL parsing during initialization."""

    @pytest.mark.parametrize(
        "url,expected_base,expected_key",
        [
            ("https://example.com/p/test-key", "https://example.com", "test-key"),
            (
                "https://markpost.example.com/p/abc123xyz",
                "https://markpost.example.com",
                "abc123xyz",
            ),
            ("http://localhost:8080/p/dev-key", "http://localhost:8080", "dev-key"),
        ],
    )
    def test_extract_url_components(self, url, expected_base, expected_key):
        """Test URL parsing during client initialization."""
        config = MarkpostConfig(url=url, timeout=30)
        client = MarkpostClient(config)
        assert client.base_url == expected_base
        assert client.post_key == expected_key

    def test_extract_invalid_url(self):
        """Test invalid URL raises exception during client initialization."""
        import pydantic

        with pytest.raises((ProgressException, pydantic.ValidationError)):
            config = MarkpostConfig(url="not-a-url", timeout=30)  # ty: ignore[invalid-argument-type]
            MarkpostClient(config)

    def test_extract_missing_path(self):
        """Test URL without path raises exception."""
        with pytest.raises(ProgressException, match="missing path"):
            config = MarkpostConfig(url="https://example.com", timeout=30)  # ty: ignore[invalid-argument-type]
            MarkpostClient(config)


class TestUrlMasking:
    """Test URL masking for logging."""

    def test_mask_url(self):
        """Test URL masking function."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)
        masked = client._mask_url("https://example.com/p/sensitive-key")
        assert "sensitive-key" not in masked
        assert "***" in masked

    def test_mask_short_key(self):
        """Test masking short keys."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)
        masked = client._mask_url("https://example.com/p/ab")
        assert "ab" not in masked or "***" in masked


class TestUpload:
    """Test upload method."""

    async def test_upload_success(self):
        """Test successful upload."""

        class FakeResponse:
            status = 200

            def raise_for_status(self):
                pass

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = AsyncMock(return_value={"id": "test123"})

            session = MagicMock()
            session.post.return_value.__aenter__.return_value = resp
            session.post.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            url = await client.upload("content", "title")
            assert url == "https://example.com/test123"

    async def test_upload_empty_content(self):
        """Test upload with empty content raises exception."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="Content cannot be empty"):
            await client.upload("")

    async def test_upload_missing_id_field(self):
        """Test upload when API response missing 'id' field."""

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls:
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = AsyncMock(return_value={})

            session = MagicMock()
            session.post.return_value.__aenter__.return_value = resp
            session.post.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            with pytest.raises(ProgressException, match="missing 'id'"):
                await client.upload("content", "title")

    async def test_upload_4xx_error_no_retry(self):
        """Test 4XX HTTP errors are reported with their status and not retried."""
        call_count = []

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls:
            resp = MagicMock()
            resp.raise_for_status = MagicMock(
                side_effect=_client_response_error(400, "Bad Request")
            )

            session = MagicMock()

            def counting_post(*args, **kwargs):
                call_count.append(1)
                return session.post.return_value

            session.post.side_effect = counting_post
            session.post.return_value.__aenter__.return_value = resp
            session.post.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            with pytest.raises(ClientError, match="Client error 400"):
                await client.upload("content", "title")

            assert len(call_count) == 1, "4XX errors should not be retried"

    async def test_upload_5xx_error_with_retry(self):
        """Test 5XX errors are retried (3 attempts total)."""
        call_count = []

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with (
            patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls,
            patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock),
        ):
            resp = MagicMock()
            resp.raise_for_status = MagicMock(
                side_effect=_client_response_error(500, "Internal server error")
            )

            session = MagicMock()

            def counting_post(*args, **kwargs):
                call_count.append(1)
                return session.post.return_value

            session.post.side_effect = counting_post
            session.post.return_value.__aenter__.return_value = resp
            session.post.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            with pytest.raises(aiohttp.ClientError):
                await client.upload("content", "title")

            assert len(call_count) == 3, "5XX errors should be retried 3 times"


class TestGetStatus:
    """Test get_status method."""

    async def test_get_status_exists(self):
        """Test checking existing post."""

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls:
            resp = MagicMock()
            resp.status = 200

            session = MagicMock()
            session.get.return_value.__aenter__.return_value = resp
            session.get.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            assert await client.get_status("abc123") is True

    async def test_get_status_not_found(self):
        """Test checking non-existent post."""

        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with patch("progress.utils.markpost.aiohttp.ClientSession") as mock_session_cls:
            resp = MagicMock()
            resp.status = 404

            session = MagicMock()
            session.get.return_value.__aenter__.return_value = resp
            session.get.return_value.__aexit__.return_value = None

            mock_session_cls.return_value.__aenter__.return_value = session

            assert await client.get_status("abc123") is False

    async def test_get_status_empty_id(self):
        """Test get_status with empty post_id."""
        config = MarkpostConfig(url="https://example.com/p/key", timeout=30)  # ty: ignore[invalid-argument-type]
        client = MarkpostClient(config)

        with pytest.raises(ProgressException, match="Post ID cannot be empty"):
            await client.get_status("")
