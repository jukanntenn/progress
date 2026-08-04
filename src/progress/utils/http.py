"""aiohttp ClientSession factory + tenacity retry helpers (spec 07).

Each entry point (CLI / API) owns its own session via the async context manager
below; sessions are never shared across ``asyncio.run`` boundaries.

Proxy handling: the session is created with ``trust_env=False`` so it (and any
client sharing the process) never picks up ``HTTP_PROXY``/``HTTPS_PROXY`` env
vars. Only GitHub traffic needs the configured proxy; that is applied per-
request via the ``ProxiedGitHubAPI`` adapter (spec 07) which threads a
``proxy=`` kwarg into each ``session.request`` call. Keeping the env var unset
avoids leaking the GitHub proxy into Feishu/MarkPost/AI/Miniflux traffic.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
import logging
from typing import Any

import aiohttp
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from progress.errors import ExternalServiceException

logger = logging.getLogger(__name__)

HTTP_TIMEOUT: int = 30
HTTP_RETRIES: int = 3
HTTP_RETRY_INITIAL_DELAY: float = 1.0
HTTP_RETRY_MAX_DELAY: float = 60.0


@asynccontextmanager
async def session_factory(
    timeout: int = HTTP_TIMEOUT,
    *,
    proxy: str | None = None,
) -> AsyncIterator[aiohttp.ClientSession]:
    """Create an aiohttp.ClientSession bound to the current event loop.

    Per spec 07, the session is closed on exit; never reuse across runs.

    ``proxy`` is accepted for backwards compatibility but intentionally unused
    here: applying it via env vars (the old approach) forced every HTTP client
    in the process through the GitHub proxy. Callers that need the proxy (only
    GitHub) pass it per-request via ``ProxiedGitHubAPI``.
    """
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout),
        trust_env=False,
    )
    try:
        yield session
    finally:
        await session.close()


async def retry_async(
    func: Callable[..., Any],
    *args: Any,
    retries: int = HTTP_RETRIES,
    initial_delay: float = HTTP_RETRY_INITIAL_DELAY,
    max_delay: float = HTTP_RETRY_MAX_DELAY,
    retry_on: type[Exception] | tuple[type[Exception], ...] = (
        ExternalServiceException,
        aiohttp.ClientError,
    ),
    **kwargs: Any,
) -> Any:
    """Run ``func(*args, **kwargs)`` with tenacity-driven exponential backoff.

    ``reraise=True`` means the original exception (not ``RetryError``) propagates
    when the retry budget is exhausted, so callers can catch specific exception
    types. Each retry is logged at WARNING via ``before_sleep_log`` so backoff
    storms are observable.
    """
    retrying = AsyncRetrying(
        stop=stop_after_attempt(retries),
        wait=wait_exponential_jitter(initial=initial_delay, max=max_delay),
        retry=retry_if_exception_type(retry_on),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    return await retrying(func, *args, **kwargs)


__all__ = [
    "HTTP_RETRIES",
    "HTTP_RETRY_INITIAL_DELAY",
    "HTTP_RETRY_MAX_DELAY",
    "HTTP_TIMEOUT",
    "retry_async",
    "session_factory",
]
