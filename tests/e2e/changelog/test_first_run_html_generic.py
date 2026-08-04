"""E2E: changelog integration first-run html_generic (spec 15 §2.6).

First run with the ``html_generic`` parser (heuristic heading-element scan).
Verifies the HTML path (the second built-in strategy), covering both parsers.
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.changelog.models import ChangelogTracker
from tests.e2e.conftest import db_view, seed_config

_HTML = """\
<html><body>
<h3>uTools v7.5.1</h3><p>Bug fixes and performance improvements.</p>
<h3>uTools 7.5</h3><p>Initial public release.</p>
</body></html>
"""


@pytest.mark.asyncio
async def test_first_run_html_generic(
    test_cfg: Any,
    httpserver: Any,
) -> None:
    httpserver.expect_request("/utools.html").respond_with_data(_HTML, content_type="text/html")
    url = httpserver.url_for("/utools.html")

    changelog_cfg = ChangelogIntegrationConfig(
        trackers=[ChangelogItemConfig(name="uTools", url=url, parser_type="html_generic")],
    )
    async with seed_config(test_cfg.state_home, "changelog", changelog_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 0

    cl_result = outcome.results["changelog"]
    assert cl_result.status == "success"
    assert len(cl_result.reports) == 1

    new_entries = cl_result.reports[0].payload.get("new_entries", [])
    assert len(new_entries) == 1
    assert new_entries[0]["version"] == "7.5.1"

    async with db_view(test_cfg.state_home):
        rows = await ChangelogTracker.all()
        assert len(rows) == 1
        assert rows[0].last_seen_version == "7.5.1"
