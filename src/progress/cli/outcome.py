from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from progress.errors import ConfigException, ProgressException

if TYPE_CHECKING:
    from collections.abc import Iterable

    from progress.cli.notifications.events import Event
    from progress.integrations.base import RunResult

EXIT_SUCCESS = 0
EXIT_PARTIAL_FAILURE = 1
EXIT_CONFIG_ERROR = 2


@dataclass
class RunOutcome:
    """Aggregated result of one ``core.run()`` invocation (spec 05/10).

    ``results`` holds each integration's ``RunResult``. ``report_events``
    holds the ``ReportEvent`` instances produced by the reports pipeline —
    they are dispatched together with each integration's own ``events``
    through ``all_events()``.
    """

    results: dict[str, RunResult] = field(default_factory=dict)
    errors: list[ProgressException] = field(default_factory=list)
    report_events: list[Event] = field(default_factory=list)

    def add(self, name: str, result: RunResult) -> None:
        self.results[name] = result
        self.errors.extend(result.errors)

    def add_report_events(self, events: Iterable[Event]) -> None:
        """Append ``ReportEvent`` instances produced by the reports pipeline."""
        self.report_events.extend(events)

    def all_events(self) -> list[Event]:
        """All events to dispatch, per spec 10.

        Order: integration-produced events first (in registration order),
        then reports-pipeline-produced ``ReportEvent`` instances.
        """
        events: list[Event] = []
        for result in self.results.values():
            events.extend(result.events)
        events.extend(self.report_events)
        return events

    @property
    def exit_code(self) -> int:
        """Exit code per spec 05.

        - ``0`` all integrations succeeded.
        - ``1`` one or more integrations reported a non-config failure
          (partial failure).
        - ``2`` a config error (:class:`ConfigException`) was collected — the
          system could not run as configured. Takes precedence over partial
          failures so a misconfiguration is surfaced distinctly.
        """
        if not self.errors:
            return EXIT_SUCCESS
        if any(isinstance(e, ConfigException) for e in self.errors):
            return EXIT_CONFIG_ERROR
        return EXIT_PARTIAL_FAILURE
