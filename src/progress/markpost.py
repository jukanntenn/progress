"""Markpost client module for publishing content."""

import logging
from urllib.parse import urlparse
from typing import NoReturn, Optional

import requests

from .config import MarkpostConfig
from .errors import ClientError, ProgressException
from .utils import retry, sanitize

logger = logging.getLogger(__name__)


def _handle_request_exception(exception: requests.RequestException, operation: str) -> NoReturn:
    """Handle RequestException by logging and raising ProgressException.

    Args:
        exception: The RequestException from requests library
        operation: Description of the operation being performed (e.g., "upload to Markpost")

    Raises:
        ProgressException: Always raises with formatted error message
    """
    status_code = getattr(exception.response, 'status_code', 'N/A')
    logger.error(
        f"Failed to {operation}: status_code={status_code}"
    )
    raise ProgressException(
        f"Failed to {operation} (status: {status_code})"
    ) from exception


class MarkpostClient:
    """Client for uploading content to Markpost service."""

    def __init__(self, config: MarkpostConfig):
        """Initialize Markpost client.

        Args:
            config: MarkpostConfig instance with url and timeout settings

        Raises:
            ProgressException: If URL format is invalid
        """
        full_url = str(config.url)
        parsed_url = urlparse(full_url)

        if not parsed_url.scheme or not parsed_url.netloc:
            raise ProgressException("Invalid markpost URL format: missing scheme or netloc")

        path = parsed_url.path.rstrip('/')
        if not path:
            raise ProgressException("Invalid markpost URL: missing path")

        parts = path.split('/')
        if len(parts) < 2:
            raise ProgressException("Invalid markpost URL: path too short")

        self.base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        self.post_key = parts[-1]
        if not self.post_key:
            raise ProgressException("Invalid markpost URL: empty post key")

        self.timeout = config.timeout

        logger.debug(
            f"MarkpostClient initialized: "
            f"base_url={self.base_url}, "
            f"post_key={sanitize(self.post_key)}, "
            f"timeout={self.timeout}"
        )

    @staticmethod
    def _check_http_status(_args, _kwargs, error, _attempt):
        status_code = getattr(error.response, 'status_code', None) if hasattr(error, 'response') else None
        if status_code and 400 <= status_code < 500:
            raise ClientError(f"Client error {status_code}: not retrying") from error

    @retry(
        times=3,
        initial_delay=5,
        backoff="exponential",
        exceptions=(requests.RequestException,),
        on_retry=lambda args, kwargs, error, attempt: MarkpostClient._check_http_status(args, kwargs, error, attempt),
    )
    def upload(self, content: str, title: Optional[str] = None) -> str:
        """Upload content to Markpost and return the published URL.

        Args:
            content: Content body to publish (required)
            title: Content title (optional)

        Returns:
            Full URL of the published post (e.g., https://example.com/p/abc123)

        Raises:
            ProgressException: If upload fails due to network or server error

        Example:
            >>> config = MarkpostConfig(url="https://markpost.example.com/p/key")
            >>> client = MarkpostClient(config)
            >>> url = client.upload("Hello World", title="My Post")
            >>> print(url)
            https://markpost.example.com/p/xyz789
        """
        if not content:
            raise ProgressException("Content cannot be empty")

        url = f"{self.base_url}/{self.post_key}"
        payload = {"title": title or "", "body": content}

        logger.info(f"Uploading content to Markpost: {self._mask_url(url)}")
        response = requests.post(url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        result = response.json()
        post_id = result.get("id")

        if not post_id:
            logger.error("Markpost API response missing 'id' field")
            raise ProgressException("Invalid Markpost API response: missing 'id'")

        published_url = f"{self.base_url}/{post_id}"
        logger.info(f"Content uploaded successfully: {published_url}")
        return published_url

    def upload_batch(
        self,
        content: str,
        title: Optional[str] = None,
        batch_index: int = 0,
        total_batches: int = 1,
    ) -> str:
        """Upload a batch of content to Markpost with batch suffix in title.

        Args:
            content: Content body to publish
            title: Content title (batch suffix will be appended if total_batches > 1)
            batch_index: Current batch index (0-based)
            total_batches: Total number of batches

        Returns:
            Full URL of the published post

        Raises:
            ProgressException: If upload fails

        Note:
            When total_batches > 1, appends " (n/m)" suffix to title
        """
        final_title = title
        if total_batches > 1 and title:
            final_title = f"{title} ({batch_index + 1}/{total_batches})"

        logger.info(
            f"Uploading batch {batch_index + 1}/{total_batches} "
            f"({len(content.encode('utf-8'))} bytes)"
        )

        return self.upload(content, final_title)

    def get_status(self, post_id: str) -> bool:
        """Check if a post exists by ID.

        Args:
            post_id: The nanoid of the post

        Returns:
            True if post exists (HTTP 200), False otherwise

        Raises:
            ProgressException: If network error occurs

        Note:
            The Markpost GET /:id endpoint returns HTML rather than JSON.
            This method only checks the HTTP status code to verify existence.
            API documentation is unclear about exact response format.
        """
        if not post_id:
            raise ProgressException("Post ID cannot be empty")

        url = f"{self.base_url}/{post_id}"

        try:
            logger.debug(f"Checking post status: {sanitize(post_id)}")
            response = requests.get(url, timeout=self.timeout)

            exists = response.status_code == 200
            logger.debug(
                f"Post {sanitize(post_id)} status: "
                f"{'exists' if exists else 'not found'}"
            )
            return exists

        except requests.RequestException as e:
            _handle_request_exception(e, "check post status")

    def _mask_url(self, url: str) -> str:
        """Mask sensitive information in URL for logging.

        Args:
            url: Full URL with post_key

        Returns:
            Masked URL with post_key partially hidden

        Example:
            >>> client = MarkpostClient(config)
            >>> client._mask_url("https://example.com/p/sensitive-key")
            'https://example.com/p/se***ey'
        """
        parsed = urlparse(url)
        path = parsed.path.rstrip('/')

        if path:
            parts = path.split('/')
            if len(parts) >= 2:
                parts[-1] = sanitize(parts[-1])
                path = '/'.join(parts)

        return f"{parsed.scheme}://{parsed.netloc}{path}"
