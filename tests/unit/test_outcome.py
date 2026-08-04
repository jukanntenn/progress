"""Unit tests for ``RunOutcome`` (spec 05/10)."""

from __future__ import annotations

from progress.cli.notifications.events import DiscoveredRepoEvent, ReportEvent
from progress.cli.outcome import RunOutcome
from progress.errors import ConfigException, ProgressException
from progress.integrations.base import RunResult


class TestAllEvents:
    def test_collects_integration_events(self) -> None:
        outcome = RunOutcome()
        result = RunResult(name="repo")
        result.events.append(DiscoveredRepoEvent(owner="o", name="n"))
        outcome.add("repo", result)
        assert len(outcome.all_events()) == 1
        assert isinstance(outcome.all_events()[0], DiscoveredRepoEvent)

    def test_collects_report_events_after_integration_events(self) -> None:
        outcome = RunOutcome()
        result = RunResult(name="repo")
        result.events.append(DiscoveredRepoEvent(owner="o", name="n"))
        outcome.add("repo", result)
        outcome.add_report_events([ReportEvent(title="t", summary="s")])
        events = outcome.all_events()
        assert len(events) == 2
        assert isinstance(events[0], DiscoveredRepoEvent)
        assert isinstance(events[1], ReportEvent)

    def test_empty_when_nothing_produced(self) -> None:
        outcome = RunOutcome()
        assert outcome.all_events() == []


class TestExitCode:
    def test_zero_when_no_errors(self) -> None:
        outcome = RunOutcome()
        assert outcome.exit_code == 0

    def test_one_on_partial_failure(self) -> None:
        outcome = RunOutcome()
        outcome.add("repo", RunResult(name="repo", errors=[ProgressException("x")]))
        assert outcome.exit_code == 1

    def test_two_on_config_error_takes_precedence(self) -> None:
        outcome = RunOutcome()
        outcome.add(
            "repo",
            RunResult(name="repo", errors=[ProgressException("a"), ConfigException("b")]),
        )
        assert outcome.exit_code == 2

    def test_aggregates_errors_across_integrations(self) -> None:
        outcome = RunOutcome()
        outcome.add("repo", RunResult(name="repo", errors=[ProgressException("a")]))
        outcome.add("changelog", RunResult(name="changelog", errors=[ProgressException("b")]))
        assert len(outcome.errors) == 2
        assert outcome.exit_code == 1
