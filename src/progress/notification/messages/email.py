from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from typing import Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...consts import TEMPLATE_EMAIL_NOTIFICATION
from ...i18n import gettext as _
from ..channels.email import EmailChannel
from ..utils import (
    ChangelogEntry,
    DiscoveredRepo,
    NotificationType,
    add_batch_indicator,
    compute_notification_stats,
)
from .base import Message

logger = logging.getLogger(__name__)


class EmailMessage(Message):
    def __init__(
        self,
        channel: EmailChannel,
        title: str,
        summary: str,
        total_commits: int,
        markpost_url: str | None = None,
        repo_statuses: Mapping[str, str] | None = None,
        notification_type: NotificationType = "repo_update",
        changelog_entries: list[ChangelogEntry] | None = None,
        discovered_repos: list[DiscoveredRepo] | None = None,
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
        self._discovered_repos = discovered_repos
        self._batch_index = batch_index
        self._total_batches = total_batches

        template_dir = Path(__file__).resolve().parents[2] / "templates"
        self._jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._jinja_env.globals["_"] = _

    def get_channel(self) -> EmailChannel:
        return self._channel

    def get_payload(self) -> str:
        subject_with_batch = add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        if self._notification_type == "changelog":
            html_content = self._build_changelog_html()
        elif self._notification_type == "discovered_repos":
            html_content = self._build_discovered_repos_html()
        else:
            html_content = self._build_default_html()
        logger.debug("Prepared email payload for %s", subject_with_batch)
        return f"Subject: {subject_with_batch}\n\n{html_content}"

    def _build_default_html(self) -> str:
        stats = compute_notification_stats(self._repo_statuses)
        template = self._jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        return template.render(
            subject=self._title,
            summary=self._summary,
            total_commits=self._total_commits,
            total_repos=stats.total_repos,
            success_count=stats.success_count,
            failed_count=stats.failed_count,
            skipped_count=stats.skipped_count,
            failed_repos=list(stats.failed_repos),
            skipped_repos=list(stats.skipped_repos),
            markpost_url=self._markpost_url,
        )

    def _build_changelog_html(self) -> str:
        items = "".join(
            f'<li><a href="{escape(e.url, quote=True)}">{escape(e.name)} {escape(e.version)}</a></li>'
            for e in (self._changelog_entries or [])
        )
        report_link = ""
        if self._markpost_url:
            report_link = (
                f'<p><a href="{escape(self._markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return (
            "<html><body>"
            f"<h2>{escape(self._title)}</h2>"
            f"<ul>{items}</ul>"
            f"{report_link}"
            "</body></html>"
        )

    def _build_discovered_repos_html(self) -> str:
        repos = self._discovered_repos or []
        visible = repos[:5]
        items = "".join(
            f'<li><a href="{escape(r.url, quote=True)}">{escape(r.name)}</a></li>'
            for r in visible
        )
        if len(repos) > 5:
            items += f"<li>... and {len(repos) - 5} more</li>"
        report_link = ""
        if self._markpost_url:
            report_link = (
                f'<p><a href="{escape(self._markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return (
            "<html><body>"
            f"<h2>{escape(self._title)}</h2>"
            f"<ul>{items}</ul>"
            f"{report_link}"
            "</body></html>"
        )


class EmailProposalMessage(Message):
    def __init__(
        self,
        channel: EmailChannel,
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

    def get_channel(self) -> EmailChannel:
        return self._channel

    def get_payload(self) -> str:
        lines: list[str] = [f"<h2>{escape(self._title)}</h2>", "<ul>"]
        for fname in self._filenames:
            lines.append(f"<li>📄 {escape(fname)}</li>")
        if self._more_count > 0:
            lines.append(f"<li>... and {self._more_count} more</li>")
        lines.append("</ul>")
        if self._markpost_url:
            lines.append(
                f'<p><a href="{escape(self._markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return f"Subject: {escape(self._title)}\n\n<html><body>{''.join(lines)}</body></html>"
