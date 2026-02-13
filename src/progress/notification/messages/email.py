from __future__ import annotations

import logging
from pathlib import Path
from typing import Mapping

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ...consts import TEMPLATE_EMAIL_NOTIFICATION
from ...i18n import gettext as _
from ..channels.email import EmailChannel
from ..utils import add_batch_indicator, compute_notification_stats
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
        stats = compute_notification_stats(self._repo_statuses)
        template = self._jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        html_content = template.render(
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

        subject_with_batch = add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        logger.debug("Prepared email payload for %s", subject_with_batch)
        return f"Subject: {subject_with_batch}\n\n{html_content}"
