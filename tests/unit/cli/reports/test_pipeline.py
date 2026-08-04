"""Unit tests for the reports pipeline fixes (spec fix-acceptance-run-issues).

Covers:
- Fix 3: ``collect_outcome`` builds ``repo_statuses`` from
  ``section.payload["status"]`` (falling back to ``result.status``), so a
  ``partial`` integration with per-section ``failed``/``success`` statuses is
  not flattened to all-``partial``.
- Fix 7: ``render_sections`` skips ``status="skipped"`` sections so they do
  not appear in the aggregated markdown detail (but ``repo_statuses`` still
  includes them for the stats row).
"""

from __future__ import annotations

from progress.cli.outcome import RunOutcome
from progress.cli.reports.pipeline import (
    ReportContext,
    collect_outcome,
    render_sections,
)
from progress.integrations.base import ReportSection, RunResult


async def test_collect_outcome_reads_per_repo_status_from_payload() -> None:
    outcome = RunOutcome()
    result = RunResult(name="repo", status="partial")
    result.reports = [
        ReportSection(
            title="r1",
            payload={"report_type": "repo_update", "status": "success"},
        ),
        ReportSection(
            title="r2",
            payload={"report_type": "repo_update", "status": "failed"},
        ),
    ]
    outcome.results["repo"] = result

    contexts = collect_outcome(outcome, generation_time="test")

    assert len(contexts) == 1
    assert contexts[0].repo_statuses == {"r1": "success", "r2": "failed"}


async def test_render_sections_skips_skipped_status_sections() -> None:
    outcome = RunOutcome()
    outcome.results["repo"] = RunResult(name="repo")
    sections_input = [
        ReportSection(title="s", payload={"status": "skipped"}),
        ReportSection(
            title="ok",
            payload={
                "status": "success",
                "report_type": "repo_update",
                "commit_count": 0,
                "releases": None,
                "repo_name": "ok",
                "repo_web_url": "",
                "branch": "main",
                "commits": [],
                "analysis_summary": "",
                "analysis_detail": "",
                "truncated": False,
                "original_diff_length": 0,
                "analyzed_diff_length": 0,
                "current_commit": "",
                "previous_commit": None,
            },
        ),
    ]
    ctx = ReportContext(
        outcome=outcome,
        integration_name="repo",
        report_type="repo_update",
        sections_input=sections_input,
    )

    render_sections(ctx)

    assert len(ctx.rendered_sections) == 1
