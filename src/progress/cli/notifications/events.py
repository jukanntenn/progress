"""Notification event types (pure data, spec 10).

Two event families coexist:

- **Business events** (``ProposalEvent`` / ``ChangelogEvent`` /
  ``DiscoveredRepoEvent`` / ``ReportEvent``) are domain-level "what happened"
  records produced by integrations. They drive snapshots, checkpoints and
  observability. They are NOT dispatched to notification channels.

- **Notification events** (``NotificationEvent``) are the only events the
  Dispatcher consumes. Each integration authors its own aggregated
  notification(s) via its ``build_notification`` hook (one per report type),
  carrying everything the channel templates need (title, summary, markpost URL
  and an integration-defined ``data`` payload).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReportRepo:
    """One repo entry in a report event."""

    name: str
    status: str = "success"
    summary: str = ""


@dataclass
class ReportEvent:
    """Aggregated report ready for notification.

    Per spec 09/10, repo_update reports may be split into multiple MarkPost
    batches; each batch dispatches one ``ReportEvent`` carrying its own
    ``batch_index`` / ``total_batches`` / ``batch_commit_count`` /
    ``batch_repo_statuses``. Other integration reports (proposal/changelog)
    emit exactly one ``ReportEvent`` per run.
    """

    title: str
    summary: str
    kind: str = "report"
    report_url: str = ""
    repos: list[ReportRepo] = field(default_factory=list)
    batch_index: int = 0
    total_batches: int = 1
    batch_commit_count: int = 0
    batch_repo_statuses: list[ReportRepo] = field(default_factory=list)


@dataclass
class ProposalEvent:
    """A proposal lifecycle event (new / accepted / rejected / …).

    Per spec proposal §15.2, one event per notifiable report. ``summary``
    carries the AI analysis summary (empty string when AI analysis failed or
    was skipped, e.g. for deletions).
    """

    proposal_kind: str = ""
    number: int = 0
    title: str = ""
    status: str = ""
    url: str = ""
    summary: str = ""
    file_path: str = ""
    kind: str = "proposal"


@dataclass
class ChangelogEvent:
    """A new changelog version was detected.

    Per spec changelog §7.2, each tracker that produced new versions emits
    exactly one event carrying the *latest* new version. ``description`` is
    that version's body text.
    """

    name: str
    version: str
    kind: str = "changelog"
    url: str = ""
    body: str = ""
    description: str = ""


@dataclass
class DiscoveredRepoEvent:
    """A new repository was discovered under a tracked owner.

    Per spec repo §10.2, ``readme_summary`` / ``readme_detail`` carry the AI
    analysis of the discovered repo's README (fallback text on AI failure).
    ``discovered_at`` is the repo's creation timestamp (rendered in the report
    badge) — empty string when the upstream timestamp was unavailable.
    """

    owner: str
    name: str
    kind: str = "discovered_repo"
    url: str = ""
    description: str = ""
    readme_summary: str = ""
    readme_detail: str = ""
    discovered_at: str = ""


@dataclass
class NotificationEvent:
    """An aggregated notification authored by one integration.

    The integration's ``build_notification`` hook produces one ``NotificationEvent``
    per report type it wants to notify on (e.g. the repo integration emits up to
    two: ``repo_update`` for tracked commits/releases and ``discovered_repo`` for
    newly discovered repositories). This is the **only** event type the Dispatcher
    consumes; per-item business events are kept for snapshots/observability.

    - ``kind`` selects the notification template directory
      (``notifications/<kind>/{html,card_json,plain_text}.j2``), co-located in
      the owning integration per spec 06.
    - ``title`` / ``summary`` are the AI-generated aggregate title/summary
      (injected from the pipeline's :class:`IntegrationReport`).
    - ``markpost_url`` is the published report's first batch URL (empty when
      MarkPost is disabled).
    - ``data`` is the integration-defined payload rendered into the templates
      (e.g. proposal ``filenames`` / ``more_count``, changelog ``entries``,
      repo ``repo_statuses`` / ``total_commits``).
    """

    kind: str
    title: str
    summary: str = ""
    markpost_url: str = ""
    batch_index: int = 0
    total_batches: int = 1
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestNotificationEvent:
    """A test notification event (kind='test') for verifying channel reachability.

    Sent via the config console 'test notification' action. Carries no business
    data; templates render a fixed i18n test message.
    """

    kind: str = "test"


Event = ReportEvent | ProposalEvent | ChangelogEvent | DiscoveredRepoEvent | NotificationEvent | TestNotificationEvent


__all__ = [
    "ChangelogEvent",
    "DiscoveredRepoEvent",
    "Event",
    "NotificationEvent",
    "ProposalEvent",
    "ReportEvent",
    "ReportRepo",
    "TestNotificationEvent",
]
