"""E2E: changelog disabled tracker skipped, no timestamp stamp (spec 15 §2.6).

One enabled + one disabled tracker: the disabled one is skipped and its
``last_check_time`` is NOT stamped (it never performed a real check). Verifies
the ``skipped`` state's "no timestamp stamping" semantics (spec changelog §2).
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from progress.integrations.changelog.models import ChangelogTracker
from tests.e2e.conftest import db_view, seed_config

_MD = """\
# Changelog

## [1.0.0] - 2024-04-01
Initial release.
"""


@pytest.mark.asyncio
async def test_disabled_tracker_skipped(
    test_cfg: Any,
    httpserver: Any,
) -> None:
    httpserver.expect_request("/ok.md").respond_with_data(_MD)
    httpserver.expect_request("/off.md").respond_with_data(_MD)
    ok_url = httpserver.url_for("/ok.md")
    off_url = httpserver.url_for("/off.md")

    changelog_cfg = ChangelogIntegrationConfig(
        trackers=[
            ChangelogItemConfig(name="OK", url=ok_url, enabled=True),
            ChangelogItemConfig(name="Off", url=off_url, enabled=False),
        ],
    )
    async with seed_config(test_cfg.state_home, "changelog", changelog_cfg):
        pass

    outcome = await run(test_cfg)
    assert outcome.exit_code == 0
    cl_result = outcome.results["changelog"]
    assert cl_result.status == "success"
    assert len(cl_result.reports) == 1
    assert cl_result.reports[0].title == "OK"

    async with db_view(test_cfg.state_home):
        rows = {r.name: r for r in await ChangelogTracker.all()}
        assert rows["OK"].last_check_time is not None
        assert rows["Off"].last_check_time is None
        assert rows["Off"].last_seen_version is None
