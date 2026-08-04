"""API tests for report endpoints (spec 12, 15)."""

from __future__ import annotations


class TestListReports:
    async def test_empty_returns_200(self, client) -> None:
        resp = await client.get("/api/v1/reports")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["page"] == 1
        assert body["page_size"] == 20
        assert body["total"] == 0
        assert body["has_next"] is False

    async def test_returns_reports_newest_first(self, db_with_reports, client) -> None:
        resp = await client.get("/api/v1/reports")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        titles = [item["title"] for item in body["items"]]
        assert "Second report" in titles
        assert "First report" in titles

    async def test_pagination(self, db_with_reports, client) -> None:
        resp = await client.get("/api/v1/reports", params={"page": 1, "page_size": 1})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["page"] == 1
        assert body["page_size"] == 1
        assert body["total"] == 2
        assert body["has_next"] is True

    async def test_filter_by_report_type(self, db_with_reports, client) -> None:
        resp = await client.get("/api/v1/reports", params={"report_type": "changelog_update"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["report_type"] == "changelog_update"

    async def test_invalid_page_returns_422(self, client) -> None:
        resp = await client.get("/api/v1/reports", params={"page": 0})
        assert resp.status_code == 422

    async def test_invalid_page_size_returns_422(self, client) -> None:
        resp = await client.get("/api/v1/reports", params={"page_size": 0})
        assert resp.status_code == 422
        resp = await client.get("/api/v1/reports", params={"page_size": 101})
        assert resp.status_code == 422


class TestGetReport:
    async def test_returns_detail_with_rendered_html(self, db_with_reports, client) -> None:
        listing = await client.get("/api/v1/reports")
        report_id = listing.json()["items"][0]["id"]

        resp = await client.get(f"/api/v1/reports/{report_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == report_id
        assert body["title"]
        assert body["content"]
        assert body["rendered_html"]
        assert "<" in body["rendered_html"]

    async def test_404_when_not_found(self, client) -> None:
        resp = await client.get("/api/v1/reports/9999")
        assert resp.status_code == 404
        body = resp.json()
        assert "error" in body
        assert body["error"]["code"] == "client_error"


class TestGetReportRaw:
    async def test_returns_raw_markdown(self, db_with_reports, client) -> None:
        listing = await client.get("/api/v1/reports")
        report_id = listing.json()["items"][0]["id"]

        resp = await client.get(f"/api/v1/reports/{report_id}/raw")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == report_id
        assert body["markdown"]
        assert "rendered_html" not in body

    async def test_404_when_not_found(self, client) -> None:
        resp = await client.get("/api/v1/reports/9999/raw")
        assert resp.status_code == 404
