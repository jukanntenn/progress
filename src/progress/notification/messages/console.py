from __future__ import annotations

import logging
from typing import Mapping, NamedTuple

from ...i18n import gettext as _
from ..channels.console import ConsoleChannel
from ..utils import (
    ChangelogEntry,
    DiscoveredRepo,
    NotificationType,
    add_batch_indicator,
    compute_notification_stats,
)
from .base import Message

logger = logging.getLogger(__name__)


class ConsoleContext(NamedTuple):
    title: str
    summary: str
    total_commits: int
    markpost_url: str | None = None
    repo_statuses: Mapping[str, str] | None = None
    notification_type: NotificationType = "repo_update"
    changelog_entries: list[ChangelogEntry] | None = None
    discovered_repos: list[DiscoveredRepo] | None = None
    batch_index: int | None = None
    total_batches: int | None = None


class ConsoleProposalContext(NamedTuple):
    title: str
    markpost_url: str | None = None
    filenames: list[str] | None = None
    more_count: int = 0


class ConsoleMessage(Message):
    def __init__(self, channel: ConsoleChannel) -> None:
        super().__init__(channel)

    def get_payload(self, context: ConsoleContext) -> str:
        title_with_batch = add_batch_indicator(
            context.title, context.batch_index, context.total_batches
        )
        if context.notification_type == "changelog":
            return self._build_changelog_payload(title_with_batch, context)
        if context.notification_type == "discovered_repos":
            return self._build_discovered_repos_payload(title_with_batch, context)
        return self._build_default_payload(title_with_batch, context)

    def _build_default_payload(self, title: str, context: ConsoleContext) -> str:
        stats = compute_notification_stats(context.repo_statuses)
        lines = [
            title,
            "",
            f"{_('Overview')}: {context.summary}",
            "",
            f"{_('Total Repositories')}: {stats.total_repos}",
            f"{_('Total Commits')}: {context.total_commits}",
            f"{_('Successful')}: {stats.success_count}",
            f"{_('Failed')}: {stats.failed_count}",
        ]
        if stats.skipped_count:
            lines.append(f"{_('Skipped')}: {stats.skipped_count}")
        if context.markpost_url:
            lines.extend(["", context.markpost_url])
        return "\n".join(lines)

    def _build_changelog_payload(self, title: str, context: ConsoleContext) -> str:
        lines = [title, ""]
        for entry in context.changelog_entries or []:
            name_and_version = f"{entry.name} {entry.version}".strip()
            lines.append(f"• {name_and_version} - {entry.url}")
        if context.markpost_url:
            lines.extend(["", context.markpost_url])
        return "\n".join(lines)

    def _build_discovered_repos_payload(
        self, title: str, context: ConsoleContext
    ) -> str:
        lines = [title, ""]
        repos = context.discovered_repos or []
        visible = repos[:5]
        for repo in visible:
            lines.append(f"{repo.name} - {repo.url}")
        if len(repos) > 5:
            lines.append(f"... and {len(repos) - 5} more")
        if context.markpost_url:
            lines.extend(["", context.markpost_url])
        return "\n".join(lines)


class ConsoleProposalMessage(Message):
    def __init__(self, channel: ConsoleChannel) -> None:
        super().__init__(channel)

    def get_payload(self, context: ConsoleProposalContext) -> str:
        lines = [context.title, ""]
        for fname in context.filenames or []:
            lines.append(f"📄 {fname}")
        if context.more_count > 0:
            lines.append(f"... and {context.more_count} more")
        if context.markpost_url:
            lines.extend(["", context.markpost_url])
        return "\n".join(lines)
