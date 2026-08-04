"""E2E: changelog integration first-run markdown (spec 15 §2.6).

First run with the ``markdown_heading`` parser reports only the single newest
version and advances the watermark to it. Verifies the markdown path + the
"first run only 1" rule + watermark advancement that only a full ``core.run``
exercises.
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.cli.notifications.events import ChangelogEvent
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.changelog.models import ChangelogTracker
from tests.e2e.conftest import db_view, seed_config

_MD = """\
# Changelog

## [3.0.0] - 2024-06-01
Third major release.

## [2.0.0] - 2024-05-01
Second major release.

## [1.0.0] - 2024-04-01
Initial stable release.
"""


@pytest.mark.asyncio
async def test_first_run_markdown(
    test_cfg: Any,
    httpserver: Any,
) -> None:
    httpserver.expect_request("/vite.md").respond_with_data(_MD)
    url = httpserver.url_for("/vite.md")

    changelog_cfg = ChangelogIntegrationConfig(
        trackers=[ChangelogItemConfig(name="Vite", url=url, parser_type="markdown_heading")],
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
    assert new_entries[0]["version"] == "3.0.0"

    assert len(cl_result.events) == 1
    assert isinstance(cl_result.events[0], ChangelogEvent)
    assert cl_result.events[0].version == "3.0.0"

    async with db_view(test_cfg.state_home):
        rows = await ChangelogTracker.all()
        assert len(rows) == 1
        assert rows[0].last_seen_version == "3.0.0"
