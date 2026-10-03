"""The pipeline event catalog (PRFC 2026-08-31 phase 2).

Eight events, modes and granularity as public contract. Firing granularity
is streaming: the integration/report/notification families fire per subject
as it completes — equivalent to the previous T9 streaming semantics — and
barrier-style consumption is an accumulating policy listener, not a runner
mode. ``notification/build`` carries an accumulator filled by the target
integration (the sole-author contract); serial means in-order within one
dispatch with short-circuit on the first truthy value, and concurrent
dispatches do not mutually exclude — same as the previous concurrent
``build_notification`` calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from progress.kernel import declare_event

if TYPE_CHECKING:
    import aiohttp

    from progress.cli.outcome import RunOutcome
    from progress.cli.reports.pipeline import ReportOutcome
    from progress.integrations.base import RunResult


def declare_catalog() -> None:
    """(Re)declare the pipeline catalog; idempotent for tests."""
    declare_event("run/started", mode="emit", replace=True)
    declare_event("integration/pre-run", mode="waterfall", replace=True)
    declare_event("integration/post-run", mode="parallel", replace=True)
    declare_event("report/assemble", mode="waterfall", replace=True)
    declare_event("report/generated", mode="emit", replace=True)
    declare_event("notification/build", mode="serial", replace=True)
    declare_event("notification/dispatch", mode="parallel", replace=True)
    declare_event("run/completed", mode="emit", replace=True)


declare_catalog()


@dataclass
class RunStartedPayload:
    integration_names: list[str]
    trackers_only: bool = False


@dataclass
class PreRunPayload:
    """Waterfall payload; a policy sets ``vetoed`` to skip this integration."""

    name: str
    vetoed: bool = False
    reason: str = ""


@dataclass
class PostRunPayload:
    name: str
    result: RunResult


@dataclass
class AssemblePayload:
    """Waterfall around one integration's report assembly (AI, budget, i18n).

    The innermost default runs the reports pipeline for the integration;
    policy listeners may transform ``sections``/reject before it.
    """

    name: str
    outcome: RunOutcome
    session: aiohttp.ClientSession | None = None
    sections: list[Any] = field(default_factory=list)
    report_outcome: Any = None


@dataclass
class ReportGeneratedPayload:
    name: str
    report_outcome: ReportOutcome


@dataclass
class BuildPayload:
    """Serial payload; the target integration fills ``out`` (sole author)."""

    name: str
    result: RunResult
    reports: list[Any] = field(default_factory=list)
    out: list[Any] = field(default_factory=list)


@dataclass
class RunCompletedPayload:
    outcome: RunOutcome


__all__ = [
    "AssemblePayload",
    "BuildPayload",
    "PostRunPayload",
    "PreRunPayload",
    "ReportGeneratedPayload",
    "RunCompletedPayload",
    "RunStartedPayload",
    "declare_catalog",
]
