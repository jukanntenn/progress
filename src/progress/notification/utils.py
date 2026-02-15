from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

NotificationType = Literal["repo_update", "changelog", "proposal", "discovered_repos"]


@dataclass(frozen=True, slots=True)
class ChangelogEntry:
    name: str
    version: str
    url: str


@dataclass(frozen=True, slots=True)
class DiscoveredRepo:
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class NotificationStats:
    total_repos: int
    success_count: int
    failed_count: int
    skipped_count: int
    failed_repos: list[str]
    skipped_repos: list[str]


def add_batch_indicator(
    title: str, batch_index: int | None, total_batches: int | None
) -> str:
    if batch_index is not None and total_batches is not None and total_batches > 1:
        return f"{title} ({batch_index + 1}/{total_batches})"
    return title


def compute_notification_stats(
    repo_statuses: Mapping[str, str] | None,
) -> NotificationStats:
    statuses = repo_statuses or {}
    success_count = 0
    failed_repos: list[str] = []
    skipped_repos: list[str] = []

    for repo_name, status in statuses.items():
        if status == "success":
            success_count += 1
        elif status == "failed":
            failed_repos.append(repo_name)
        elif status == "skipped":
            skipped_repos.append(repo_name)

    return NotificationStats(
        total_repos=len(statuses),
        success_count=success_count,
        failed_count=len(failed_repos),
        skipped_count=len(skipped_repos),
        failed_repos=failed_repos,
        skipped_repos=skipped_repos,
    )
