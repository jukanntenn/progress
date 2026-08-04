"""E2E: changelog fetch 404 → run partial, other tracker unaffected (spec 15 §2.6).

One tracker's URL returns 404 → its status fails, but a second tracker in the
same config still succeeds. Verifies single-tracker failure does not abort the
run and errors aggregate to partial (spec changelog §11).
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.integrations.changelog.config import ChangelogIntegrationConfig, ChangelogItemConfig
from tests.e2e.conftest import seed_config

_OK_MD = """\
# Changelog

## [1.0.0] - 2024-04-01
Initial release.
"""


@pytest.mark.asyncio
async def test_fetch_404_marks_run_partial(
    test_cfg: Any,
    httpserver: Any,
) -> None:
    httpserver.expect_request("/ok.md").respond_with_data(_OK_MD)
    httpserver.expect_request("/missing.md").respond_with_data("not found", status=404)

    changelog_cfg = ChangelogIntegrationConfig(
        trackers=[
            ChangelogItemConfig(name="OK", url=httpserver.url_for("/ok.md")),
            ChangelogItemConfig(name="Missing", url=httpserver.url_for("/missing.md")),
        ],
    )
    async with seed_config(test_cfg.state_home, "changelog", changelog_cfg):
        pass

    outcome = await run(test_cfg)
    cl_result = outcome.results["changelog"]
    assert cl_result.status in {"partial", "failed"}
    assert cl_result.errors
    assert len(cl_result.reports) == 1
    assert cl_result.reports[0].title == "OK"
