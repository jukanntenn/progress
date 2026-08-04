"""Unit tests for ``RepoIntegration`` tracker fixes (spec fix-acceptance-run-issues).

Covers:
- Fix 1: commit diff failure surfaces a ``status="failed"`` section + downgrades
  ``result.status`` to ``"partial"`` (instead of the repo disappearing).
- Fix 2: ``_run_one_repo`` emits a ``status="skipped"`` minimal section when
  HEAD is unchanged and there are no new releases (instead of returning None).
- Fix 6: ``build_notification`` reads per-repo status from
  ``section.payload["status"]`` (falling back to ``result.status``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, patch

from progress.cli.ai import AnalysisResult
from progress.cli.git import RepoRef
from progress.cli.reports.pipeline import IntegrationReport
from progress.config.root import CoreConfig
from progress.errors import GitException
from progress.integrations.base import Components, ReportSection, RunResult
from progress.integrations.repo.config import RepoIntegrationConfig
from progress.integrations.repo.models import Repository
from progress.integrations.repo.release import ReleaseCheckResult, ReleaseRecord
from progress.integrations.repo.tracker import RepoIntegration

if TYPE_CHECKING:
    from pathlib import Path


def _make_integration(tmp_path: Path) -> RepoIntegration:
    integration = RepoIntegration()
    cfg = CoreConfig(state_home=str(tmp_path))
    integration._cfg = cfg
    integration._ctx = Components(cfg=cfg)
    integration._plugin_cfg = RepoIntegrationConfig()
    return integration


async def _make_repo_row() -> Repository:
    return await Repository.create(
        url="https://github.com/o/r",
        name="r",
        branch="main",
        enabled=True,
    )


async def test_run_one_repo_marks_failed_section_when_diff_raises(tmp_path: Path) -> None:
    integration = _make_integration(tmp_path)
    repo_row = await _make_repo_row()
    result = RunResult(name="repo")

    with patch("progress.integrations.repo.tracker.clone_or_fetch", new=AsyncMock()):
        integration._check_releases_for_repo = AsyncMock(return_value=None)
        integration._compute_commit_diff = AsyncMock(side_effect=GitException("fatal: bad object"))
        await integration._run_one_repo(repo_row, repos_dir=tmp_path, result=result)

    assert result.status == "partial"
    assert len(result.errors) == 1
    assert len(result.reports) == 1
    assert result.reports[0].payload["status"] == "failed"
    assert "bad object" in result.reports[0].payload["failure_reason"]


async def test_run_one_repo_skips_when_no_changes(tmp_path: Path) -> None:
    integration = _make_integration(tmp_path)
    repo_row = await _make_repo_row()
    result = RunResult(name="repo")

    with patch("progress.integrations.repo.tracker.clone_or_fetch", new=AsyncMock()):
        integration._check_releases_for_repo = AsyncMock(return_value=ReleaseCheckResult(candidates=[]))
        integration._compute_commit_diff = AsyncMock(return_value=None)
        await integration._run_one_repo(repo_row, repos_dir=tmp_path, result=result)

    # A no-change run emits a minimal status="skipped" section so the report and
    # notification pipelines see an explicit per-repo status (the render step
    # filters status="skipped" sections out of the visible report).
    assert len(result.reports) == 1
    assert result.reports[0].payload["status"] == "skipped"
    assert result.status == "success"
    assert result.errors == []


async def test_run_one_repo_emits_failed_not_skipped_when_diff_fails_and_no_releases(
    tmp_path: Path,
) -> None:
    integration = _make_integration(tmp_path)
    repo_row = await _make_repo_row()
    result = RunResult(name="repo")

    with patch("progress.integrations.repo.tracker.clone_or_fetch", new=AsyncMock()):
        integration._check_releases_for_repo = AsyncMock(return_value=None)
        integration._compute_commit_diff = AsyncMock(side_effect=GitException("fatal: bad object"))
        await integration._run_one_repo(repo_row, repos_dir=tmp_path, result=result)

    assert result.reports[0].payload["status"] == "failed"
    assert result.reports[0].payload["status"] != "skipped"
    assert result.status == "partial"


async def test_build_notification_reads_per_repo_status_from_payload() -> None:
    integration = RepoIntegration()
    result = RunResult(name="repo", status="partial")
    result.reports = [
        ReportSection(
            title="r1",
            payload={"report_type": "repo_update", "status": "success", "commit_count": 1},
        ),
        ReportSection(
            title="r2",
            payload={"report_type": "repo_update", "status": "success", "commit_count": 1},
        ),
        ReportSection(
            title="r3",
            payload={"report_type": "repo_update", "status": "failed", "commit_count": 0},
        ),
    ]
    fake_report = IntegrationReport(
        integration_name="repo",
        report_type="repo_update",
        report_id=1,
    )

    events = await integration.build_notification(result=result, reports=[fake_report])

    assert len(events) == 1
    assert events[0].kind == "repo_update"
    repo_statuses = events[0].data["repo_statuses"]
    assert len(repo_statuses) == 3
    assert list(repo_statuses.values()).count("failed") == 1
    assert list(repo_statuses.values()).count("success") == 2


async def test_build_repository_section_marks_success_status_when_no_failure(
    tmp_path: Path,
) -> None:
    integration = _make_integration(tmp_path)
    repo_row = await _make_repo_row()

    section = await integration._build_repository_section(
        repo_row=repo_row,
        ref=_make_ref(),
        dest=tmp_path,
        commit_result=None,
        release_result=None,
        commit_failed_reason=None,
    )

    assert section is not None
    assert section.payload["status"] == "success"


def _make_ref():

    return RepoRef(owner="o", name="r")


async def test_build_repository_section_sanitizes_release_notes_to_notes_html(
    tmp_path: Path,
) -> None:
    """Release notes are sanitized to balanced HTML (Bug 4).

    GitHub release bodies commonly contain their own <details>/<summary> blocks;
    emitting them raw would let an unbalanced tag swallow the AI analysis
    <details> after the markpost HTML parser rebalances. render_markdown keeps
    details/summary in the allowlist (Feature 8 batch 1) but rebalances them so
    the outer release <details> never gets swallowed, while preserving inner text.
    """

    integration = _make_integration(tmp_path)
    repo_row = await _make_repo_row()

    untrusted_notes = (
        "## What's Changed\n"
        "<details><summary>Assets</summary>changelog here"  # unbalanced: no closing tags
    )
    candidate = ReleaseRecord(
        tag="v1.0.0",
        name="v1.0.0",
        notes=untrusted_notes,
        published_at="2026-07-27T00:00:00Z",
        url="https://github.com/o/r/releases/tag/v1.0.0",
    )
    release_result = ReleaseCheckResult(candidates=[candidate])

    with patch(
        "progress.integrations.repo.tracker.analyze_release",
        new=AsyncMock(return_value=AnalysisResult(summary="sum", detail="det")),
    ):
        section = await integration._build_repository_section(
            repo_row=repo_row,
            ref=_make_ref(),
            dest=tmp_path,
            commit_result=None,
            release_result=release_result,
            commit_failed_reason=None,
        )

    assert section is not None
    notes_html = section.payload["releases"][0]["notes_html"]
    # details/summary kept (now in allowlist) but rebalanced by the sanitizer;
    # the unbalanced input gets a matching </details> so it can't swallow siblings.
    assert "<details>" in notes_html
    assert "<summary>Assets</summary>" in notes_html
    assert notes_html.count("<details>") == notes_html.count("</details>")
    assert "Assets" in notes_html
    assert "changelog here" in notes_html
    # the raw untrusted notes are NOT carried into the template payload
    assert "notes" not in section.payload["releases"][0]
