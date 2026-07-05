"""Notification dispatch: channel orchestration and entity-specific senders."""

from __future__ import annotations

import logging
import typing
from datetime import datetime
from pathlib import PurePath
from typing import Unpack
from zoneinfo import ZoneInfo

from ..ai import Analyzer
from ..config import Config
from ..contrib.changelog.changelog_tracker import ChangelogCheckResult
from ..contrib.proposal import ProposalReport
from ..contrib.repo.reporter import MarkdownReporter
from ..db import save_report
from ..i18n import gettext as _
from ..reporting import generate_title_and_summary, publish_monolithic_report
from ..contrib.proposal.types import KIND_CONFIGS
from ..templates import render
from ..telemetry import record_notification_sent
from ..utils.markpost import MarkpostClient
from ..utils.timezone import get_now
from .config import NotificationConfig
from .factory import create_message, create_proposal_message
from .utils import ChangelogEntry, DiscoveredRepo, NotificationType

logger = logging.getLogger(__name__)


class _NotificationData(typing.TypedDict, total=False):
    title: str
    summary: str
    total_commits: int
    markpost_url: str | None
    repo_statuses: typing.Mapping[str, str] | None
    notification_type: NotificationType
    changelog_entries: list[ChangelogEntry] | None
    discovered_repos: list[DiscoveredRepo] | None
    batch_index: int | None
    total_batches: int | None
    filenames: list[str] | None
    more_count: int


def send_notification(
    notification_config: NotificationConfig,
    *,
    is_proposal: bool = False,
    **data: Unpack[_NotificationData],
) -> None:
    if not notification_config.channels:
        return

    enabled_channels = [c for c in notification_config.channels if c.enabled]
    if not enabled_channels:
        return

    failures = 0
    for channel_config in enabled_channels:
        if is_proposal:
            message = create_proposal_message(channel_config)
            context = _build_proposal_context(channel_config.type, **data)
        else:
            message = create_message(channel_config)
            context = _build_notification_context(channel_config.type, **data)
        if not message.send(context, fail_silently=True):
            failures += 1
        else:
            record_notification_sent(channel=channel_config.type)

    if failures:
        logger.warning(
            "Some notifications failed: %s/%s", failures, len(enabled_channels)
        )


def _build_notification_context(
    channel_type: str, **data: Unpack[_NotificationData]
) -> object:
    from .messages import ConsoleContext, EmailContext, FeishuContext

    title = data.get("title", "")
    summary = data.get("summary", "")
    total_commits = data.get("total_commits", 0)
    markpost_url = data.get("markpost_url")
    repo_statuses = data.get("repo_statuses")
    notification_type = data.get("notification_type", "repo_update")
    changelog_entries = data.get("changelog_entries")
    discovered_repos = data.get("discovered_repos")
    batch_index = data.get("batch_index")
    total_batches = data.get("total_batches")

    if channel_type == "feishu":
        return FeishuContext(
            title=title,
            summary=summary,
            total_commits=total_commits,
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
            notification_type=notification_type,
            changelog_entries=changelog_entries,
            discovered_repos=discovered_repos,
            batch_index=batch_index,
            total_batches=total_batches,
        )
    if channel_type == "email":
        return EmailContext(
            title=title,
            summary=summary,
            total_commits=total_commits,
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
            notification_type=notification_type,
            changelog_entries=changelog_entries,
            discovered_repos=discovered_repos,
            batch_index=batch_index,
            total_batches=total_batches,
        )
    return ConsoleContext(
        title=title,
        summary=summary,
        total_commits=total_commits,
        markpost_url=markpost_url,
        repo_statuses=repo_statuses,
        notification_type=notification_type,
        changelog_entries=changelog_entries,
        discovered_repos=discovered_repos,
        batch_index=batch_index,
        total_batches=total_batches,
    )


def _build_proposal_context(
    channel_type: str, **data: Unpack[_NotificationData]
) -> object:
    from .messages import (
        ConsoleProposalContext,
        EmailProposalContext,
        FeishuProposalContext,
    )

    title = data.get("title", "")
    markpost_url = data.get("markpost_url")
    filenames = data.get("filenames")
    more_count = data.get("more_count", 0)

    if channel_type == "feishu":
        return FeishuProposalContext(
            title=title,
            markpost_url=markpost_url,
            filenames=filenames,
            more_count=more_count,
        )
    if channel_type == "email":
        return EmailProposalContext(
            title=title,
            markpost_url=markpost_url,
            filenames=filenames,
            more_count=more_count,
        )
    return ConsoleProposalContext(
        title=title,
        markpost_url=markpost_url,
        filenames=filenames,
        more_count=more_count,
    )


def send_entity_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
    analyzer: Analyzer,
    new_repos: list[dict[str, object]],
    timezone: ZoneInfo,
) -> None:
    if not new_repos:
        return

    sorted_repos = sorted(
        new_repos, key=lambda r: r.get("created_at") or datetime.min, reverse=True
    )

    for r in sorted_repos:
        r.setdefault("readme_summary", None)
        r.setdefault("readme_detail", None)

    for r in sorted_repos:
        created_at = r.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            if isinstance(created_at, datetime):
                r["discovered_at"] = created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                r["discovered_at"] = "Unknown"
        else:
            r["discovered_at"] = "Unknown"

        if "owner_name" not in r:
            name_with_owner = r.get("name_with_owner", "")
            if isinstance(name_with_owner, str) and "/" in name_with_owner:
                r["owner_name"] = name_with_owner.split("/")[0]
            else:
                r["owner_name"] = "Unknown"

    reporter = MarkdownReporter()
    report_content = reporter.generate_discovered_repos_report(sorted_repos, timezone)

    try:
        title, summary = generate_title_and_summary(
            analyzer, report_content, config.analysis.language
        )
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for owner monitoring: {e}")
        now = get_now(timezone)
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=now.strftime("%Y-%m-%d %H:%M")
        )
        summary = f"Discovered {len(new_repos)} new repositories"

    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="repo_new",
        commit_count=len(new_repos),
    )
    markpost_url = publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    discovered_repos = [
        DiscoveredRepo(
            name=str(
                r.get("name_with_owner") or r.get("repo_name") or r.get("id")
            ),
            url=str(
                r.get("repo_url")
                or f"https://github.com/{r.get('name_with_owner', '')}"
            ),
        )
        for r in sorted_repos
    ]

    send_notification(
        notification_config,
        title=title,
        summary=summary or f"Discovered {len(new_repos)} new repositories",
        total_commits=0,
        markpost_url=markpost_url,
        notification_type="discovered_repos",
        discovered_repos=discovered_repos,
    )


def send_proposal_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
    analyzer: Analyzer,
    reports: list[ProposalReport],
    timezone: ZoneInfo,
) -> None:
    grouped: dict[str, list[ProposalReport]] = {}
    for r in reports:
        grouped.setdefault(r.kind.value, []).append(r)

    for k in grouped:
        grouped[k] = sorted(grouped[k], key=lambda x: x.number)

    tracker_urls = {k.value: KIND_CONFIGS[k].repo_url for k in KIND_CONFIGS}

    now = get_now(timezone)
    report_content = render(
        "proposal_events_report.j2",
        grouped_events=grouped,
        tracker_urls=tracker_urls,
        generation_time=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )

    try:
        title, summary = generate_title_and_summary(
            analyzer, report_content, config.analysis.language
        )
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for proposal events: {e}")
        title = "Proposal Updates"
        summary = ""

    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="proposal",
        commit_count=len(reports),
    )
    markpost_url = publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    filenames = [PurePath(r.file_path).name for r in reports][:5]
    more_count = max(0, len(reports) - len(filenames))
    send_notification(
        notification_config,
        is_proposal=True,
        title=title,
        summary=summary,
        total_commits=len(reports),
        markpost_url=markpost_url,
        filenames=filenames,
        more_count=more_count,
    )


def send_changelog_update_notification(
    config: Config,
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient | None,
    updates: list[ChangelogCheckResult],
    all_results: list[ChangelogCheckResult],
    timezone: ZoneInfo,
) -> None:
    now = get_now(timezone)
    report_content = render(
        "changelog_updates_report.j2",
        now=now.strftime("%Y-%m-%d %H:%M"),
        generation_time=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        updates=updates,
    )

    title = f"Changelog Updates - {now.strftime('%Y-%m-%d %H:%M')}"

    total_new_versions = sum(len(u.new_entries) for u in updates)
    report_id = save_report(
        config=config,
        title=title,
        content=report_content,
        report_type="changelog",
        commit_count=total_new_versions,
    )
    markpost_url = publish_monolithic_report(
        report_id=report_id,
        title=title,
        body=report_content,
        config=config,
        markpost_client=markpost_client,
    )

    parts = [f"{u.name} ({len(u.new_entries)})" for u in updates]
    summary = (
        f"{len(updates)} trackers updated, {total_new_versions} new versions: "
        + ", ".join(parts[:10])
    )
    if len(parts) > 10:
        summary += f", ... and {len(parts) - 10} more"

    changelog_entries = [
        ChangelogEntry(name=u.name, version=u.new_entries[0].version, url=u.url)
        for u in updates
    ]

    send_notification(
        notification_config,
        title=title,
        summary=summary,
        total_commits=total_new_versions,
        markpost_url=markpost_url,
        notification_type="changelog",
        changelog_entries=changelog_entries,
    )
