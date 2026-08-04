"""API tests for the test-notification endpoint (Feature 7)."""

from __future__ import annotations

import pytest

from progress.api.routes._limiter import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Reset the in-memory rate-limit counters between tests (shared limiter)."""
    limiter.reset()
    yield
    limiter.reset()


class TestTestNotifications:
    async def test_returns_summary_in_valid_set(self, client) -> None:
        resp = await client.post("/api/v1/config/notifications/test")
        assert resp.status_code == 200
        body = resp.json()
        # default notification config has no channels enabled (console is opt-in)
        assert body["summary"] in ("ok", "no_channels", "partial_failure")
        assert isinstance(body["results"], list)

    async def test_rate_limit_3_per_minute(self, client) -> None:
        # The first 3 requests within the window must succeed.
        for _ in range(3):
            resp = await client.post("/api/v1/config/notifications/test")
            assert resp.status_code == 200
        # The 4th request is rate-limited (429).
        resp = await client.post("/api/v1/config/notifications/test")
        assert resp.status_code == 429

    async def test_accept_language_header_accepted(self, client) -> None:
        # The locale middleware must not reject any Accept-Language value;
        # a zh-hans header should localize the rendered test message.
        resp = await client.post(
            "/api/v1/config/notifications/test",
            headers={"Accept-Language": "zh-hans"},
        )
        assert resp.status_code == 200
