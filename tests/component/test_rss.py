"""API tests for the RSS feed endpoint (spec 12, 15)."""

from __future__ import annotations

from progress.db.models.report import Report


class TestRssFeed:
    async def test_returns_rss_xml(self, client) -> None:
        resp = await client.get("/api/v1/rss")
        assert resp.status_code == 200
        assert "xml" in resp.headers["content-type"]
        body = resp.text
        assert "<?xml" in body
        assert "<rss" in body
        assert "<channel>" in body

    async def test_includes_reports(self, db_with_reports, client) -> None:
        resp = await client.get("/api/v1/rss")
        assert resp.status_code == 200
        body = resp.text
        assert "<item>" in body
        assert "First report" in body or "Second report" in body

    async def test_empty_feed_still_valid(self, client) -> None:
        resp = await client.get("/api/v1/rss")
        assert resp.status_code == 200
        body = resp.text
        assert "<?xml" in body
        assert "<channel>" in body
        assert "<item>" not in body

    async def test_limit_param(self, db_with_reports, client) -> None:
        resp = await client.get("/api/v1/rss", params={"limit": 1})
        assert resp.status_code == 200
        body = resp.text
        assert body.count("<item>") == 1

    async def test_invalid_limit_returns_422(self, client) -> None:
        resp = await client.get("/api/v1/rss", params={"limit": 0})
        assert resp.status_code == 422
        resp = await client.get("/api/v1/rss", params={"limit": 201})
        assert resp.status_code == 422

    async def test_uses_markpost_url_when_present(self, client) -> None:
        await Report.create(
            report_type="aggregated",
            title="With URL",
            content="body",
            commit_hash="h",
            commit_count=1,
            markpost_url="https://markpost.example/123",
        )
        resp = await client.get("/api/v1/rss")
        assert resp.status_code == 200
        body = resp.text
        assert "https://markpost.example/123" in body
