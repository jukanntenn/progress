"""Rule-guard tests for the severe-exception → Bugsink wiring policy.

Policy (single source of truth: ``progress.observability.report_severe``):
every caught exception is reported, including graceful-degradation paths
(AI unavailable, external service down). The only exempt catches are probes /
multi-format tries / filters / cleanup that belong to the normal
business-logic chain. These tests pin both sides of that boundary at
representative sites, and assert the degradation behavior itself is unchanged.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from progress.cli.git.local import get_commit_hash_at
from progress.cli.notifications.base import ChannelPayload, ContentType, SendResult
from progress.cli.notifications.dispatcher import Dispatcher
from progress.cli.notifications.events import NotificationEvent, TestNotificationEvent
from progress.cli.notifications.renderer import JinjaRenderer
from progress.cli.outcome import RunOutcome
from progress.cli.reports.pipeline import run_for_integration
from progress.config.root import AnalysisConfig, CoreConfig
from progress.errors import CommandException, ProgressException
from progress.integrations.base import ReportSection, RunResult
from progress.integrations.repo.analysis import TruncatedDiff, analyze_commit_diff


def _outcome_with_one_repo_section() -> RunOutcome:
    outcome = RunOutcome()
    result = RunResult(name="repo", status="success")
    result.reports.append(
        ReportSection(
            title="vitejs/vite",
            content="# Vite\n\nbody",
            payload={
                "repo_name": "vitejs/vite",
                "repo_web_url": "https://github.com/vitejs/vite",
                "commits": [],
                "status": "success",
                "truncated": False,
            },
        )
    )
    outcome.add("repo", result)
    return outcome


class TestPipelineWiring:
    async def test_persist_failure_reports_and_degrades(self) -> None:
        """A DB failure inside ``persist`` must reach Bugsink with the real
        exception while the pipeline outcome keeps its degraded shape
        (error recorded, status downgraded) instead of crashing."""
        outcome = _outcome_with_one_repo_section()
        with (
            patch(
                "progress.cli.reports.pipeline.persist",
                side_effect=RuntimeError("db down"),
            ),
            patch("progress.cli.reports.pipeline.report_severe") as report,
        ):
            result = await run_for_integration(outcome, CoreConfig(), "repo")
        report.assert_called_once()
        assert isinstance(report.call_args.args[0], RuntimeError)
        assert result.status == "partial"
        assert result.errors and "db down" in str(result.errors[0])

    async def test_ai_title_summary_failure_reports(self) -> None:
        """Rule inversion guard: even the expected AI-unavailable degradation
        (ProgressException from ``run_extraction``) is reported — degradation
        semantics stay (default title, empty summary)."""
        outcome = _outcome_with_one_repo_section()
        with (
            patch(
                "progress.cli.reports.pipeline.generate_title_summary",
                side_effect=ProgressException("AI down"),
            ),
            patch("progress.cli.reports.pipeline.report_severe") as report,
        ):
            result = await run_for_integration(outcome, CoreConfig(), "repo")
        report.assert_called_once()
        assert isinstance(report.call_args.args[0], ProgressException)
        assert result.errors


class TestAiDegradationWiring:
    async def test_commit_diff_ai_failure_reports_and_falls_back(self) -> None:
        truncated = TruncatedDiff(text="diff", truncated=False, original_length=4, analyzed_length=4)
        with (
            patch(
                "progress.integrations.repo.analysis._run_analysis",
                side_effect=ProgressException("AI unavailable"),
            ),
            patch("progress.integrations.repo.analysis.report_severe") as report,
        ):
            result = await analyze_commit_diff(
                repo_name="vitejs/vite",
                branch="main",
                diff_text="diff",
                commit_messages=[],
                truncated=truncated,
                cfg=AnalysisConfig(),
            )
        report.assert_called_once()
        assert result.summary == "**AI analysis unavailable for vitejs/vite**"
        assert result.detail == ""


class TestNotificationWiring:
    def test_renderer_failure_reports_and_falls_back(self) -> None:
        """An unknown/broken template must fall back to plain text (existing
        behavior) AND be reported — previously this was fully silent."""
        event = NotificationEvent(kind="bogus_kind", title="t")
        with patch("progress.cli.notifications.renderer.report_severe") as report:
            payload = JinjaRenderer(None).render(event, ContentType.PLAIN_TEXT)
        report.assert_called_once()
        assert payload.title == "t"

    async def test_dispatcher_channel_failure_reports(self) -> None:
        """A channel send exception is collected into SendResult (existing
        behavior) and reported with the full exception for Bugsink."""

        class FailingChannel:
            name = "failing"

            async def send(self, payload: ChannelPayload) -> SendResult:
                raise RuntimeError("smtp down")

        class StaticRenderer:
            def render(self, event: object, content_type: ContentType) -> ChannelPayload:
                return ChannelPayload(title="t", body="b", content_type=content_type)

        with patch("progress.cli.notifications.dispatcher.report_severe") as report:
            outcome = await Dispatcher([FailingChannel()], StaticRenderer()).dispatch(TestNotificationEvent())
        report.assert_called_once()
        assert isinstance(report.call_args.args[0], RuntimeError)
        assert not outcome.ok
        assert outcome.results[0].channel == "failing"
        assert not outcome.results[0].ok
        assert "smtp down" in (outcome.results[0].error or "")


class TestWhitelistGuards:
    async def test_git_rev_probe_stays_silent(self, tmp_path) -> None:
        """Whitelist guard: ``rev-parse --verify`` failing is the documented
        probe for "rev does not exist" (spec repo §5.3) — a normal
        business-logic chain, so it must NOT be reported."""
        with (
            patch(
                "progress.cli.git.local._run_git",
                AsyncMock(side_effect=CommandException("rev not found")),
            ),
            patch("progress.cli.git.local.report_severe") as report,
        ):
            assert await get_commit_hash_at(tmp_path, "HEAD~3") is None
        report.assert_not_called()
