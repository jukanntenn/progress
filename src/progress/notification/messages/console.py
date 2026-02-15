from __future__ import annotations

from typing import Mapping

from ...i18n import gettext as _
from ..channels.console import ConsoleChannel
from ..utils import (
    ChangelogEntry,
    NotificationType,
    add_batch_indicator,
    compute_notification_stats,
)
from .base import Message


class ConsoleMessage(Message):
    def __init__(
        self,
        channel: ConsoleChannel,
        title: str,
        summary: str,
        total_commits: int,
        markpost_url: str | None = None,
        repo_statuses: Mapping[str, str] | None = None,
        notification_type: NotificationType = "repo_update",
        changelog_entries: list[ChangelogEntry] | None = None,
        batch_index: int | None = None,
        total_batches: int | None = None,
    ) -> None:
        super().__init__(channel)
        self._title = title
        self._summary = summary
        self._total_commits = total_commits
        self._markpost_url = markpost_url
        self._repo_statuses = repo_statuses
        self._notification_type = notification_type
        self._changelog_entries = changelog_entries
        self._batch_index = batch_index
        self._total_batches = total_batches

    def get_channel(self) -> ConsoleChannel:
        return self._channel

    def get_payload(self) -> str:
        title_with_batch = add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        if self._notification_type == "changelog":
            return self._build_changelog_payload(title_with_batch)
        return self._build_default_payload(title_with_batch)

    def _build_default_payload(self, title: str) -> str:
        stats = compute_notification_stats(self._repo_statuses)
        lines = [
            title,
            "",
            f"{_('Overview')}: {self._summary}",
            "",
            f"{_('Total Repositories')}: {stats.total_repos}",
            f"{_('Total Commits')}: {self._total_commits}",
            f"{_('Successful')}: {stats.success_count}",
            f"{_('Failed')}: {stats.failed_count}",
        ]
        if stats.skipped_count:
            lines.append(f"{_('Skipped')}: {stats.skipped_count}")
        if self._markpost_url:
            lines.extend(["", self._markpost_url])
        return "\n".join(lines)

    def _build_changelog_payload(self, title: str) -> str:
        lines = [title, ""]
        for entry in self._changelog_entries or []:
            name_and_version = f"{entry.name} {entry.version}".strip()
            lines.append(f"• {name_and_version} - {entry.url}")
        if self._markpost_url:
            lines.extend(["", self._markpost_url])
        return "\n".join(lines)


class ConsoleProposalMessage(Message):
    def __init__(
        self,
        channel: ConsoleChannel,
        title: str,
        markpost_url: str | None = None,
        filenames: list[str] | None = None,
        more_count: int = 0,
    ) -> None:
        super().__init__(channel)
        self._title = title
        self._markpost_url = markpost_url
        self._filenames = filenames or []
        self._more_count = more_count

    def get_channel(self) -> ConsoleChannel:
        return self._channel

    def get_payload(self) -> str:
        lines = [self._title, ""]
        for fname in self._filenames:
            lines.append(f"📄 {fname}")
        if self._more_count > 0:
            lines.append(f"... and {self._more_count} more")
        if self._markpost_url:
            lines.extend(["", self._markpost_url])
        return "\n".join(lines)
