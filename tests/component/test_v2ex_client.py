"""Component tests for the V2EX HTTP client (spec v2ex §3/§8, test decisions).

pytest-httpserver serves local HTML; ``base_url`` points at it. Covers:
- fetch_tab / fetch_topic_body happy path
- 403 → ProgressException, NOT retried (ban signal)
- 503 / 429 → ExternalServiceException, retried via retry_async
- per-request ``proxy=`` kwarg propagation (mirrors ProxiedGitHubAPI)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aiohttp
import pytest
from werkzeug.wrappers import Response

from progress.errors import ExternalServiceException, ProgressException
from progress.integrations.v2ex import client as v2ex_client
from progress.integrations.v2ex.client import V2EX_USER_AGENT, V2exClient

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer

JOBS_BODY = (
    '<html><body><div class="cell item">'
    '<span class="item_title"><a href="/t/100#reply1" id="topic-link-100" class="topic-link">t</a></span>'
    "</div></body></html>"
)
TOPIC_BODY_HTML = '<html><body><div class="topic_content"><p>Rust backend, remote.</p></div></body></html>'


@pytest.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


def _client(session: aiohttp.ClientSession, httpserver: HTTPServer, *, proxy: str | None = None) -> V2exClient:
    return V2exClient(session, httpserver.url_for("").rstrip("/"), proxy)


def _fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch retry_async to zero-delay so retry tests don't sleep."""
    real = v2ex_client.retry_async

    async def _fast(func, *args, **kwargs):
        return await real(func, *args, initial_delay=0, max_delay=0, **kwargs)

    monkeypatch.setattr(v2ex_client, "retry_async", _fast)


class TestFetchTab:
    async def test_returns_html(self, session: aiohttp.ClientSession, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/").respond_with_data(JOBS_BODY)
        html = await _client(session, httpserver).fetch_tab("jobs")
        assert "topic-link-100" in html

    async def test_sends_browser_user_agent(self, session: aiohttp.ClientSession, httpserver: HTTPServer) -> None:
        captured: dict[str, str] = {}

        def _handler(req):
            captured["ua"] = req.headers.get("User-Agent", "")

            return Response(JOBS_BODY)

        httpserver.expect_request("/").respond_with_handler(_handler)
        await _client(session, httpserver).fetch_tab("jobs")
        assert captured["ua"] == V2EX_USER_AGENT


class TestFetchTopicBody:
    async def test_extracts_topic_content_html(self, session: aiohttp.ClientSession, httpserver: HTTPServer) -> None:
        httpserver.expect_request("/t/100").respond_with_data(TOPIC_BODY_HTML)
        body = await _client(session, httpserver).fetch_topic_body(100)
        assert "<p>Rust backend, remote.</p>" in body

    async def test_missing_topic_content_returns_empty(
        self, session: aiohttp.ClientSession, httpserver: HTTPServer
    ) -> None:
        httpserver.expect_request("/t/1").respond_with_data("<html><body>no content</body></html>")
        assert await _client(session, httpserver).fetch_topic_body(1) == ""


class TestErrorHandling:
    async def test_403_raises_progress_exception_not_retried(
        self,
        session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = {"n": 0}

        def _handler(req):
            calls["n"] += 1

            return Response("forbidden", status=403)

        httpserver.expect_request("/").respond_with_handler(_handler)
        _fast_retry(monkeypatch)
        with pytest.raises(ProgressException):
            await _client(session, httpserver).fetch_tab("jobs")
        assert calls["n"] == 1  # 403 not retried

    async def test_503_retried_then_raises(
        self,
        session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = {"n": 0}

        def _handler(req):
            calls["n"] += 1

            return Response("down", status=503)

        httpserver.expect_request("/").respond_with_handler(_handler)
        _fast_retry(monkeypatch)
        with pytest.raises(ExternalServiceException):
            await _client(session, httpserver).fetch_tab("jobs")
        assert calls["n"] > 1  # retried

    async def test_503_then_success(
        self,
        session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = {"n": 0}

        def _handler(req):
            calls["n"] += 1

            if calls["n"] < 3:
                return Response("down", status=503)
            return Response(JOBS_BODY)

        httpserver.expect_request("/").respond_with_handler(_handler)
        _fast_retry(monkeypatch)
        html = await _client(session, httpserver).fetch_tab("jobs")
        assert "topic-link-100" in html
        assert calls["n"] == 3

    async def test_429_retried(
        self,
        session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls = {"n": 0}

        def _handler(req):
            calls["n"] += 1

            return Response("rate", status=429) if calls["n"] == 1 else Response(JOBS_BODY)

        httpserver.expect_request("/").respond_with_handler(_handler)
        _fast_retry(monkeypatch)
        await _client(session, httpserver).fetch_tab("jobs")
        assert calls["n"] == 2


class _FakeResponse:
    def __init__(self) -> None:
        self.status = 200
        self.charset = "utf-8"

    async def text(self) -> str:
        return "ok"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class _FakeSession:
    def __init__(self) -> None:
        self.captured: dict[str, Any] = {}

    def get(self, url, **kwargs):
        self.captured = {"url": url, **kwargs}
        return _FakeResponse()


class TestProxyPropagation:
    async def test_proxy_passed_per_request(self) -> None:
        fake = _FakeSession()
        client = V2exClient(fake, "http://example.com", "http://spy:8080")  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        await client.fetch_tab("jobs")
        assert fake.captured["proxy"] == "http://spy:8080"

    async def test_none_proxy_passed_through(self) -> None:
        fake = _FakeSession()
        client = V2exClient(fake, "http://example.com", None)  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        await client.fetch_topic_body(5)
        assert fake.captured["proxy"] is None
