from __future__ import annotations

import logging
from html import escape
from pathlib import Path
from typing import Mapping, NamedTuple

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


class EmailContext(NamedTuple):
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


class EmailProposalContext(NamedTuple):
    title: str
    markpost_url: str | None = None
    filenames: list[str] | None = None
    more_count: int = 0


class EmailMessage(Message):
    def __init__(self, channel: EmailChannel) -> None:
        super().__init__(channel)
        template_dir = Path(__file__).resolve().parents[2] / "templates"
        self._jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._jinja_env.globals["_"] = _

    def get_payload(self, context: EmailContext) -> str:
        subject_with_batch = add_batch_indicator(
            context.title, context.batch_index, context.total_batches
        )
        if context.notification_type == "changelog":
            html_content = self._build_changelog_html(context)
        elif context.notification_type == "discovered_repos":
            html_content = self._build_discovered_repos_html(context)
        else:
            html_content = self._build_default_html(context)
        logger.debug("Prepared email payload for %s", subject_with_batch)
        return f"Subject: {subject_with_batch}\n\n{html_content}"

    def _build_default_html(self, context: EmailContext) -> str:
        stats = compute_notification_stats(context.repo_statuses)
        template = self._jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        return template.render(
            subject=context.title,
            summary=context.summary,
            total_commits=context.total_commits,
            total_repos=stats.total_repos,
            success_count=stats.success_count,
            failed_count=stats.failed_count,
            skipped_count=stats.skipped_count,
            failed_repos=list(stats.failed_repos),
            skipped_repos=list(stats.skipped_repos),
            markpost_url=context.markpost_url,
        )

    def _build_changelog_html(self, context: EmailContext) -> str:
        items = "".join(
            f'<li><a href="{escape(e.url, quote=True)}">{escape(e.name)} {escape(e.version)}</a></li>'
            for e in (context.changelog_entries or [])
        )
        report_link = ""
        if context.markpost_url:
            report_link = (
                f'<p><a href="{escape(context.markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return (
            "<html><body>"
            f"<h2>{escape(context.title)}</h2>"
            f"<ul>{items}</ul>"
            f"{report_link}"
            "</body></html>"
        )

    def _build_discovered_repos_html(self, context: EmailContext) -> str:
        repos = context.discovered_repos or []
        visible = repos[:5]
        items = "".join(
            f'<li><a href="{escape(r.url, quote=True)}">{escape(r.name)}</a></li>'
            for r in visible
        )
        if len(repos) > 5:
            items += f"<li>... and {len(repos) - 5} more</li>"
        report_link = ""
        if context.markpost_url:
            report_link = (
                f'<p><a href="{escape(context.markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return (
            "<html><body>"
            f"<h2>{escape(context.title)}</h2>"
            f"<ul>{items}</ul>"
            f"{report_link}"
            "</body></html>"
        )


class EmailProposalMessage(Message):
    def __init__(self, channel: EmailChannel) -> None:
        super().__init__(channel)

    def get_payload(self, context: EmailProposalContext) -> str:
        lines: list[str] = [f"<h2>{escape(context.title)}</h2>", "<ul>"]
        for fname in context.filenames or []:
            lines.append(f"<li>📄 {escape(fname)}</li>")
        if context.more_count > 0:
            lines.append(f"<li>... and {context.more_count} more</li>")
        lines.append("</ul>")
        if context.markpost_url:
            lines.append(
                f'<p><a href="{escape(context.markpost_url, quote=True)}">'
                f"{escape(_('View Detailed Report'))}</a></p>"
            )
        return f"Subject: {escape(context.title)}\n\n<html><body>{''.join(lines)}</body></html>"
