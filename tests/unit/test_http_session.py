"""Unit tests for ``progress.utils.http.session_factory`` proxy isolation + the
GitHub per-request proxy adapter (spec 07).

The session must never set ``HTTP_PROXY``/``HTTPS_PROXY`` env vars (the old
approach dragged every HTTP client through the GitHub proxy). Only GitHub
traffic is proxied, via ``ProxiedGitHubAPI``.
"""

from __future__ import annotations

import os
from typing import Self

from progress.cli.git.github import ProxiedGitHubAPI
from progress.utils.http import session_factory


class TestSessionFactoryNoEnvPollution:
    async def test_does_not_set_proxy_env_vars(self) -> None:
        before = {k: os.environ.get(k) for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")}
        async with session_factory(proxy="http://proxy:7890") as session:
            for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                assert os.environ.get(k) is None
            assert session.trust_env is False
            await session.close()

        for k, v in before.items():
            assert os.environ.get(k) == v

    async def test_trust_env_always_false(self) -> None:
        async with session_factory() as session:
            assert session.trust_env is False


class TestProxiedGitHubAPI:
    async def test_request_threads_proxy_kwarg(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            status = 200

            def __init__(self) -> None:
                self.headers = {"content-type": "application/json"}

            async def read(self) -> bytes:
                return b"[]"

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

        class FakeSession:
            def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
                captured["method"] = method
                captured["url"] = url
                captured["proxy"] = kwargs.get("proxy")
                return FakeResponse()

        api = ProxiedGitHubAPI.__new__(ProxiedGitHubAPI)
        api._session = FakeSession()
        api._proxy = "http://proxy:7890"

        status, _headers, body = await api._request(
            "GET", "https://api.github.com/repos/x/y", {"Authorization": "token t"}
        )

        assert status == 200
        assert body == b"[]"
        assert captured["method"] == "GET"
        assert captured["url"] == "https://api.github.com/repos/x/y"
        assert captured["proxy"] == "http://proxy:7890"

    async def test_request_without_proxy_passes_none(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            status = 200
            headers: dict[str, str] = {}

            async def read(self) -> bytes:
                return b""

            async def __aenter__(self) -> Self:
                return self

            async def __aexit__(self, *args: object) -> None:
                pass

        class FakeSession:
            def request(self, method: str, url: str, **kwargs: object) -> FakeResponse:
                captured["proxy"] = kwargs.get("proxy")
                return FakeResponse()

        api = ProxiedGitHubAPI.__new__(ProxiedGitHubAPI)
        api._session = FakeSession()
        api._proxy = None

        await api._request("GET", "https://api.github.com/test", {})
        assert captured["proxy"] is None
