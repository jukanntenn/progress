"""E2E: v2ex integration via ``core.run()`` (spec v2ex test decisions).

Two cases (≤2 per spec):
- happy path: httpserver feeds a tab + topic bodies; AI is mocked via
  ``override_agent`` for the two result types; asserts a ``v2ex`` Report is
  persisted, the water mark advances, and the run succeeds.
- disabled: empty ``interest_profile`` → v2ex cleanly no-ops inside a full run.

AI is never called for real: ``build_model_string`` is monkeypatched so v2ex
enables without configured analysis, and each agent is overridden with a
``TestModel`` returning fixed JSON. ``ALLOW_MODEL_REQUESTS=False`` (autouse)
backstops any stray call. pytest-httpserver stands in for v2ex.com (no real
network).
"""

from __future__ import annotations

from typing import Any

import pytest

from progress.cli.core import run
from progress.db.models.report import Report
from progress.integrations.v2ex.config import V2exIntegrationConfig
from progress.integrations.v2ex.models import V2exTracker
from progress.integrations.v2ex.tracker import (
    V2exClassificationResult,
    V2exSummaryResult,
)
from tests.e2e.conftest import db_view, override_agent, seed_config

pytestmark = pytest.mark.e2e


def _cell(topic_id: int, title: str, *, replies: int = 0) -> str:
    last = "" if replies == 0 else ' • 最后回复来自 <strong><a href="/member/user_002">user_002</a></strong>'
    return (
        f'<div class="cell item"><table><tr>'
        f'<td><span class="item_title"><a href="/t/{topic_id}#reply{replies}" '
        f'id="topic-link-{topic_id}" class="topic-link">{title}</a></span>'
        f'<span class="topic_info"><a class="node" href="/go/jobs">酷工作</a> • '
        f'<strong><a href="/member/user_001">user_001</a></strong> • '
        f'<span title="2026-08-12 10:00:00 +08:00">x</span>{last}</span></td>'
        f'<td><a href="/t/{topic_id}#reply{replies}" class="count_livid">{replies}</a></td>'
        f"</tr></table></div>"
    )


def _tab_html(*cells: str) -> str:
    return f"<html><body>{''.join(cells)}</body></html>"


def _topic_html(body: str) -> str:
    return f'<html><body><div class="topic_content">{body}</div></body></html>'


CLASSIFY_JSON = (
    '{"posts": ['
    '{"post_index": 0, "interested": true, "score": 9, "reason": "rust remote"},'
    '{"post_index": 1, "interested": true, "score": 8, "reason": "go remote"},'
    '{"post_index": 2, "interested": false, "score": 0, "reason": "off-topic"}'
    "]}"
)
SUMMARY_JSON = '{"posts": [{"post_index": 0, "takeaway": "rust role"}, {"post_index": 1, "takeaway": "go role"}]}'


def _patch_v2ex(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("progress.integrations.v2ex.tracker.build_model_string", lambda _cfg: "stub:model")
    monkeypatch.setattr("progress.integrations.v2ex.tracker.V2EX_REQUEST_MIN_DELAY", 0.0)
    monkeypatch.setattr("progress.integrations.v2ex.tracker.V2EX_REQUEST_MAX_DELAY", 0.0)


@pytest.mark.asyncio
async def test_v2ex_happy_path(test_cfg: Any, httpserver: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_v2ex(monkeypatch)
    httpserver.expect_request("/").respond_with_data(
        _tab_html(_cell(200, "Rust backend"), _cell(201, "Go backend"), _cell(202, "Java backend"))
    )
    httpserver.expect_request("/t/200").respond_with_data(_topic_html("rust body"))
    httpserver.expect_request("/t/201").respond_with_data(_topic_html("go body"))

    plugin_cfg = V2exIntegrationConfig(
        base_url=httpserver.url_for("").rstrip("/"),
        interest_profile="rust/go remote backend",
        tabs=["jobs"],
        max_summaries=2,
    )
    async with seed_config(test_cfg.state_home, "v2ex", plugin_cfg):
        with (
            override_agent(V2exClassificationResult, response_text=CLASSIFY_JSON),
            override_agent(V2exSummaryResult, response_text=SUMMARY_JSON),
        ):
            outcome = await run(test_cfg)

    v2ex_result = outcome.results["v2ex"]
    assert v2ex_result.status == "success"
    assert len(v2ex_result.reports) == 1
    posts = v2ex_result.reports[0].payload["posts"]
    assert {p["title"] for p in posts} == {"Rust backend", "Go backend"}

    async with db_view(test_cfg.state_home):
        reports = await Report.filter(report_type="v2ex")
        assert len(reports) == 1
        assert reports[0].commit_count == 2
        tracker = await V2exTracker.get(source="tab:jobs")
        assert tracker.last_topic_id == 202  # advanced past all new topics


@pytest.mark.asyncio
async def test_v2ex_disabled_when_profile_empty(
    test_cfg: Any, httpserver: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_v2ex(monkeypatch)
    plugin_cfg = V2exIntegrationConfig(
        base_url=httpserver.url_for("").rstrip("/"),
        interest_profile="",  # empty → disabled
        tabs=["jobs"],
    )
    async with seed_config(test_cfg.state_home, "v2ex", plugin_cfg):
        outcome = await run(test_cfg)

    v2ex_result = outcome.results["v2ex"]
    assert v2ex_result.status == "success"
    assert v2ex_result.reports == []
    assert v2ex_result.errors == []

    async with db_view(test_cfg.state_home):
        # sync() still runs (config-driven) and creates the tab row, but run()
        # is disabled so the water mark is never advanced.
        tracker = await V2exTracker.get(source="tab:jobs")
        assert tracker.last_topic_id is None
