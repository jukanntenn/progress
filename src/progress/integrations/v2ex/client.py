"""Async HTTP client for V2EX (spec v2ex §3 / §A.6).

Native aiohttp on the shared ``ClientSession`` owned by the lifespan (spec 07).
Two deliberate deviations from the changelog HTTP template, both flagged with
inline comments:

- **Proxy per request.** The shared session is created with ``trust_env=False``
  and carries no proxy; only GitHub traffic is proxied today (via
  ``ProxiedGitHubAPI``). V2EX must likewise pass ``proxy=`` on each
  ``session.get`` so a user behind a proxy can still reach the site, reusing the
  project's single ``cfg.github.proxy`` setting (no new config field).
- **Real browser User-Agent.** changelog identifies as ``"progress"``; V2EX runs
  aggressive anti-bot, and honestly identifying as a bot on a public-content
  scrape invites blocking faster. RSSHub's v2ex route sets no custom UA either.

Retry policy (spec v2ex §8): transient ``429``/``503`` + network/timeout errors
retry via :func:`progress.utils.http.retry_async` (pure exponential jitter,
aligned with changelog). ``403`` and other 4xx raise a NON-retried
``ProgressException`` — 403 is a rate-control/ban signal and retrying it only
worsens the ban. The two-type split (``ExternalServiceException`` retried vs
``ProgressException`` not) mirrors changelog's ``_fetch_text``.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import lxml.html

from progress.errors import ExternalServiceException, ProgressException
from progress.utils.http import retry_async

logger = logging.getLogger(__name__)

V2EX_TIMEOUT: int = 30
V2EX_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
V2EX_REQUEST_MIN_DELAY: float = 3.0
V2EX_REQUEST_MAX_DELAY: float = 8.0

_HEADERS = {
    "User-Agent": V2EX_USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

_RETRY_STATUSES: frozenset[int] = frozenset({429, 503})


class V2exClient:
    """Fetch V2EX tab pages + topic bodies over the shared aiohttp session."""

    def __init__(self, session: aiohttp.ClientSession, base_url: str, proxy: str | None) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._proxy = proxy

    async def fetch_tab(self, tab: str) -> str:
        """GET ``{base_url}/?tab={tab}`` → tab page HTML."""
        return await self._get(f"{self._base_url}/?tab={tab}", what=f"tab {tab}")

    async def fetch_topic_body(self, topic_id: int) -> str:
        """GET ``{base_url}/t/{topic_id}`` → the ``topic_content`` body text.

        Only the topic's own content is extracted (replies are out of scope,
        spec v2ex §2). Returns the decoded plain text.
        """
        html = await self._get(f"{self._base_url}/t/{topic_id}", what=f"topic {topic_id}")
        return _extract_topic_content(html)

    async def _get(self, url: str, *, what: str) -> str:
        timeout = aiohttp.ClientTimeout(total=V2EX_TIMEOUT)

        async def _do_get() -> str:
            try:
                async with self._session.get(url, headers=_HEADERS, proxy=self._proxy, timeout=timeout) as resp:
                    status = resp.status
                    if status in _RETRY_STATUSES:
                        raise ExternalServiceException(f"v2ex fetch {what} failed: HTTP {status}")
                    if status >= 400:
                        # 403/4xx are not retried: 403 is a ban/rate-control signal.
                        raise ProgressException(f"v2ex fetch {what} failed: HTTP {status}")
                    return await resp.text()
            except aiohttp.ClientError as e:
                raise ExternalServiceException(f"v2ex fetch {what} network error: {e}") from e
            except TimeoutError as e:
                raise ExternalServiceException(f"v2ex fetch {what} timed out after {V2EX_TIMEOUT}s") from e

        return await retry_async(
            _do_get,
            retry_on=(ExternalServiceException, aiohttp.ClientError, asyncio.TimeoutError),
        )


def _extract_topic_content(html: str) -> str:
    """Pull the ``div.topic_content`` text out of a topic page (spec v2ex §2)."""
    tree = lxml.html.fromstring(html)
    nodes = tree.xpath('//div[contains(@class, "topic_content")]')
    if not nodes:
        return ""
    return nodes[0].text_content().strip()


__all__ = [
    "V2EX_REQUEST_MAX_DELAY",
    "V2EX_REQUEST_MIN_DELAY",
    "V2EX_TIMEOUT",
    "V2EX_USER_AGENT",
    "V2exClient",
]
