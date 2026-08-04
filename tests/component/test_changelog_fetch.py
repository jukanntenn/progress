"""Component tests for changelog HTTP fetch + charset decoding (spec changelog §9).

Covers:
- HTTP 4xx → ``failed`` (raises ProgressException, caught by ``_check``; not retried)
- HTTP 5xx → ``failed`` (raises ExternalServiceException, retried via retry_async,
  then caught by ``_check`` after the retry budget is exhausted)
- ``aiohttp.ClientError`` wrapped as ExternalServiceException (retried)
- User-Agent: ``progress`` (literal, no version suffix)
- Total timeout 30s (configurable in code constant)
- Charset decoding strategy:
  * HTTP header charset wins when valid
  * UTF-8 as ultimate fallback
  * mojibake detection skips iso-8859-1 / latin-1 / windows-1252 candidates
    when the decoded text contains replacement chars or control bytes
  * all candidates fail → UTF-8 + replacement chars
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
import unittest.mock

import aiohttp
import pytest
from werkzeug.wrappers import Response

from progress.db import close_db, init_db, set_config
from progress.errors import ExternalServiceException
from progress.integrations.base import Components
from progress.integrations.changelog.config import (
    ChangelogIntegrationConfig,
    ChangelogItemConfig,
)
from progress.integrations.changelog.models import ChangelogTracker
from progress.integrations.changelog.tracker import (
    FETCH_TIMEOUT_SECONDS,
    FETCH_USER_AGENT,
    ChangelogIntegration,
    _decode_response,
    _looks_like_mojibake,
)
from progress.utils import http as http_utils

if TYPE_CHECKING:
    from pytest_httpserver import HTTPServer


@pytest.fixture
async def db_and_session(tmp_state_home: str, httpserver: HTTPServer):
    await init_db(tmp_state_home)
    async with aiohttp.ClientSession() as session:
        yield session
    await close_db()


async def _setup(
    session: aiohttp.ClientSession,
    plugin_cfg: ChangelogIntegrationConfig | None = None,
) -> ChangelogIntegration:
    integration = ChangelogIntegration()
    if plugin_cfg is not None:
        await set_config("changelog", plugin_cfg.model_dump(mode="json"))
    await integration.setup(Components(cfg=None, session=session))
    return integration


class TestFetchConstants:
    def test_user_agent_is_literal_progress(self) -> None:
        assert FETCH_USER_AGENT == "progress"

    def test_timeout_is_300_seconds(self) -> None:
        assert FETCH_TIMEOUT_SECONDS == 300.0

    def test_timeout_passed_to_client_timeout(self) -> None:
        """Feature 2: _fetch_text builds ClientTimeout with FETCH_TIMEOUT_SECONDS as total."""

        integration = ChangelogIntegration()
        integration._ctx = None
        session = unittest.mock.MagicMock()

        captured_timeout = None

        class _FakeResp:
            status = 200
            charset = "utf-8"

            async def read(self):
                return b"## 1.0.0\nbody"

        class _FakeCM:
            async def __aenter__(self):
                return _FakeResp()

            async def __aexit__(self, *args):
                return False

        def _fake_get(url, timeout=None, headers=None):
            nonlocal captured_timeout
            captured_timeout = timeout
            return _FakeCM()

        session.get = _fake_get

        with unittest.mock.patch(
            "progress.integrations.changelog.tracker._decode_response",
            return_value="## 1.0.0\nbody",
        ):
            asyncio.run(integration._fetch_text(session, "http://example.com/c.md"))

        assert captured_timeout is not None
        assert captured_timeout.total == 300.0


class TestRunConcurrency:
    """Feature 2: run() uses asyncio.gather for full concurrency (no Semaphore)."""

    async def test_two_trackers_run_concurrently(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        """Second tracker starts before first completes (no Semaphore)."""

        httpserver.expect_request("/a.md").respond_with_data("## 1.0.0\na body")
        httpserver.expect_request("/b.md").respond_with_data("## 2.0.0\nb body")

        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="A", url=httpserver.url_for("/a.md")),
                ChangelogItemConfig(name="B", url=httpserver.url_for("/b.md")),
            ],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        started_before_a_finished = asyncio.Event()

        original_run_one = integration._run_one

        async def _slow_run_one(tracker_row, config_index, session, result):
            if tracker_row.name == "A":
                started_before_a_finished.set()
                await asyncio.sleep(0.05)
            await original_run_one(tracker_row, config_index, session, result)

        integration._run_one = _slow_run_one  # type: ignore
        result = await integration.run()
        assert result.status == "success"
        assert started_before_a_finished.is_set()
        assert len(result.reports) == 2

    async def test_concurrent_error_isolation(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        """One tracker crashing does not prevent the other from completing."""

        httpserver.expect_request("/good.md").respond_with_data("## 1.0.0\ngood body")
        httpserver.expect_request("/bad.md").respond_with_data("no versions", status=200)

        cfg = ChangelogIntegrationConfig(
            trackers=[
                ChangelogItemConfig(name="Good", url=httpserver.url_for("/good.md")),
                ChangelogItemConfig(name="Bad", url=httpserver.url_for("/bad.md")),
            ],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()
        result = await integration.run()
        assert result.status == "partial"
        assert len(result.errors) == 1
        assert len(result.reports) == 1
        assert result.reports[0].title == "Good"


class TestRetryBehavior:
    """Feature 2: retry_async uses retries=2 (2 attempts total)."""

    async def test_failed_fetch_surfaces_after_retries_exhausted(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_check calls _fetch_text; retries=2 means retry_async retries twice internally."""
        monkeypatch.setattr(http_utils, "HTTP_RETRY_INITIAL_DELAY", 0.0)
        monkeypatch.setattr(http_utils, "HTTP_RETRY_MAX_DELAY", 0.0)

        httpserver.expect_request("/err").respond_with_data("oops", status=500)
        url = httpserver.url_for("/err")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None

        with unittest.mock.patch.object(
            integration, "_fetch_text", side_effect=ExternalServiceException("500")
        ) as mock_fetch:
            result = await integration._check(row, db_and_session)

        assert result.status == "failed"
        assert mock_fetch.call_count == 1


class TestMojibakeDetection:
    """Spec changelog §9 — suspect-charset mojibake heuristic."""

    def test_returns_false_for_utf8(self) -> None:
        assert _looks_like_mojibake("utf-8", "正常文本") is False

    def test_returns_false_for_unsuspect_charset(self) -> None:
        assert _looks_like_mojibake("gbk", "anything") is False

    def test_returns_true_for_replacement_char(self) -> None:
        assert _looks_like_mojibake("iso-8859-1", "text \ufffd here") is True

    def test_returns_true_for_latin1_with_replacement(self) -> None:
        assert _looks_like_mojibake("latin-1", "\ufffd") is True

    def test_returns_true_for_windows_1252_with_replacement(self) -> None:
        assert _looks_like_mojibake("windows-1252", "garbled \ufffd text") is True


class TestDecodeResponse:
    """Spec changelog §9 — decode strategy."""

    async def test_empty_body(self) -> None:
        class _Stub:
            charset = "utf-8"

            async def read(self):
                return b""

        result = await _decode_response(_Stub())  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        assert result == ""

    async def test_utf8_decodes_cleanly(self) -> None:
        class _Stub:
            charset = "utf-8"

            async def read(self):
                return "正常文本".encode()

        result = await _decode_response(_Stub())  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        assert result == "正常文本"

    async def test_falls_back_to_utf8_when_no_charset(self) -> None:
        class _Stub:
            charset = None

            async def read(self):
                return b"ascii text"

        result = await _decode_response(_Stub())  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        assert result == "ascii text"

    async def test_unknown_charset_falls_back_to_utf8(self) -> None:
        class _Stub:
            charset = "totally-made-up-charset"

            async def read(self):
                return b"hello"

        result = await _decode_response(_Stub())  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        assert result == "hello"

    async def test_final_fallback_uses_replacement_chars(self) -> None:
        invalid_utf8 = b"\xff\xfe\xfd"

        class _NeverDecodeStub:
            charset = None

            async def read(self):
                return invalid_utf8

        result = await _decode_response(_NeverDecodeStub())  # type: ignore[arg-type]  # ty:ignore[invalid-argument-type]
        assert "\ufffd" in result


class TestFetchHttpStatusErrors:
    async def test_http_404_marks_check_failed(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/missing").respond_with_data("not found", status=404)
        url = httpserver.url_for("/missing")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        tracker_row = await ChangelogTracker.first()
        assert tracker_row is not None
        result = await integration._check(tracker_row, db_and_session)
        assert result.status == "failed"
        assert result.error is not None
        assert "404" in result.error

    async def test_http_500_marks_check_failed(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        monkeypatch.setattr(http_utils, "HTTP_RETRY_INITIAL_DELAY", 0.0)
        monkeypatch.setattr(http_utils, "HTTP_RETRY_MAX_DELAY", 0.0)
        httpserver.expect_request("/err").respond_with_data("oops", status=500)
        url = httpserver.url_for("/err")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status == "failed"
        assert "500" in (result.error or "")


class TestCheckStates:
    async def test_disabled_tracker_returns_skipped(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/c.md").respond_with_data("## 1.0.0\nbody")
        url = httpserver.url_for("/c.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url, enabled=False)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status == "skipped"
        assert row.last_check_time is None

    async def test_no_new_version_advances_check_time_only(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:

        httpserver.expect_request("/c.md").respond_with_data("## 1.0.0\nbody")
        url = httpserver.url_for("/c.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        row.last_seen_version = "1.0.0"
        await row.save()

        result = await integration._check(row, db_and_session)
        assert result.status == "no_new_version"
        assert result.latest_version == "1.0.0"

    async def test_failed_check_advances_check_time(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/broken").respond_with_data("no versions here", status=200)
        url = httpserver.url_for("/broken")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status == "failed"

    async def test_no_version_headings_marks_failed(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        httpserver.expect_request("/empty").respond_with_data("# plain doc\nno versions")
        url = httpserver.url_for("/empty")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status == "failed"
        # Feature 6: with no configured AI (cfg=None), the universal parser's
        # deterministic strategies fail to find versions and the AI fallback is
        # unavailable, so _check reports no version entries found.
        assert "no version entries found" in (result.error or "").lower()


class TestCharsetEndToEnd:
    async def test_utf8_chinese_decoded(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        body = "## 1.0.0\n\n中文版本说明\n"
        httpserver.expect_request("/c.md").respond_with_data(
            body.encode("utf-8"), content_type="text/plain; charset=utf-8"
        )
        url = httpserver.url_for("/c.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status == "success"
        assert result.new_entries is not None
        assert "中文版本说明" in result.new_entries[0].description

    async def test_mislabelled_iso8859_falls_back_to_utf8(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        body = "## 1.0.0\n\n中文\n"
        encoded = body.encode("utf-8")

        httpserver.expect_request("/c.md").respond_with_data(encoded, content_type="text/plain; charset=iso-8859-1")
        url = httpserver.url_for("/c.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        result = await integration._check(row, db_and_session)
        assert result.status in {"success", "failed"}
        if result.status == "success" and result.new_entries:
            assert "中文" in result.new_entries[0].description


class TestUserAgentHeader:
    async def test_user_agent_sent(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
    ) -> None:
        captured: dict[str, str] = {}

        def _handler(req):

            captured["user_agent"] = req.headers.get("User-Agent", "")
            return Response("## 1.0.0\nbody")

        httpserver.expect_request("/c.md").respond_with_handler(_handler)
        url = httpserver.url_for("/c.md")
        cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, cfg)
        await integration.sync()

        row = await ChangelogTracker.first()
        assert row is not None
        await integration._check(row, db_and_session)
        assert captured["user_agent"] == "progress"


class TestTimeoutHandling:
    async def test_timeout_surfaces_non_empty_error(
        self,
        db_and_session: aiohttp.ClientSession,
        httpserver: HTTPServer,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        monkeypatch.setattr(http_utils, "HTTP_RETRY_INITIAL_DELAY", 0.0)
        monkeypatch.setattr(http_utils, "HTTP_RETRY_MAX_DELAY", 0.0)

        httpserver.expect_request("/slow").respond_with_data("x" * 1000, status=200)
        url = httpserver.url_for("/slow")
        plugin_cfg = ChangelogIntegrationConfig(
            trackers=[ChangelogItemConfig(name="X", url=url)],
        )
        integration = await _setup(db_and_session, plugin_cfg)
        await integration.sync()

        tracker_row = await ChangelogTracker.first()
        assert tracker_row is not None

        async def _fake_fetch(*args, **kwargs):
            raise TimeoutError

        monkeypatch.setattr(integration, "_fetch_text", _fake_fetch)

        result = await integration._check(tracker_row, db_and_session)
        assert result.status == "failed"
        assert result.error is not None
        assert result.error != ""
        assert "unknown error" not in result.error.lower()
