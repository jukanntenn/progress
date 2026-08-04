"""E2E: changelog incremental multiple new versions (spec 15 §2.6).

Second run where the log gains 3 new versions: the report renders ALL 3, the
watermark advances to the first (newest), but only ONE ChangelogEvent is emitted
carrying the single newest. Verifies the "report renders all vs notification
sends only latest 1" separation (spec changelog §1.5) — the changelog headline.
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.cli.notifications.events import ChangelogEvent
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.changelog.models import ChangelogTracker
from tests.e2e.conftest import db_view, seed_config

_INITIAL = """\
# Changelog

## [1.0.0] - 2024-04-01
Initial stable release.
"""

_INCREMENTED = """\
# Changelog

## [4.0.0] - 2024-07-01
Fourth major release.

## [3.0.0] - 2024-06-01
Third major release.

## [2.0.0] - 2024-05-01
Second major release.

## [1.0.0] - 2024-04-01
Initial stable release.
"""


@pytest.mark.asyncio
async def test_incremental_multiple_new_versions(
    test_cfg: Any,
    httpserver: Any,
) -> None:
    httpserver.expect_request("/vite.md").respond_with_data(_INITIAL)
    url = httpserver.url_for("/vite.md")

    changelog_cfg = ChangelogIntegrationConfig(
        trackers=[ChangelogItemConfig(name="Vite", url=url, parser_type="markdown_heading")],
    )
    async with seed_config(test_cfg.state_home, "changelog", changelog_cfg):
        pass

    first = await run(test_cfg)
    assert first.exit_code == 0
    assert first.results["changelog"].reports[0].payload["new_entries"][0]["version"] == "1.0.0"

    httpserver.clear_all_handlers()
    httpserver.expect_request("/vite.md").respond_with_data(_INCREMENTED)

    second = await run(test_cfg)
    assert second.exit_code == 0
    cl_result = second.results["changelog"]
    assert cl_result.status == "success"
    assert len(cl_result.reports) == 1

    new_entries = cl_result.reports[0].payload.get("new_entries", [])
    versions = [e["version"] for e in new_entries]
    assert versions == ["4.0.0", "3.0.0", "2.0.0"]

    events = [e for e in cl_result.events if isinstance(e, ChangelogEvent)]
    assert len(events) == 1
    assert events[0].version == "4.0.0"

    async with db_view(test_cfg.state_home):
        rows = await ChangelogTracker.all()
        assert rows[0].last_seen_version == "4.0.0"
