from __future__ import annotations

from typing import Mapping

from ...i18n import gettext as _
from ..channels.console import ConsoleChannel
from ..utils import add_batch_indicator, compute_notification_stats
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
        batch_index: int | None = None,
        total_batches: int | None = None,
    ) -> None:
        super().__init__(channel)
        self._title = title
        self._summary = summary
        self._total_commits = total_commits
        self._markpost_url = markpost_url
        self._repo_statuses = repo_statuses
        self._batch_index = batch_index
        self._total_batches = total_batches

    def get_channel(self) -> ConsoleChannel:
        return self._channel

    def get_payload(self) -> str:
        title_with_batch = add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        stats = compute_notification_stats(self._repo_statuses)
        lines = [
            title_with_batch,
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
