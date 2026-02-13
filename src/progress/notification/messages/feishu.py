from __future__ import annotations

import json
import logging
from typing import Any, Mapping

from ...i18n import gettext as _
from ..channels.feishu import FeishuChannel
from ..utils import add_batch_indicator, compute_notification_stats
from .base import Message

logger = logging.getLogger(__name__)


class FeishuMessage(Message):
    def __init__(
        self,
        channel: FeishuChannel,
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

    def get_channel(self) -> FeishuChannel:
        return self._channel

    def get_payload(self) -> str:
        title_with_batch = add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        card = {
            "msg_type": "interactive",
            "card": {
                "header": self._build_header(title_with_batch),
                "elements": self._build_elements(),
            },
        }
        logger.debug("Prepared Feishu payload for %s", title_with_batch)
        return json.dumps(card, ensure_ascii=False)

    def _build_header(self, title: str) -> dict[str, Any]:
        return {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        }

    def _build_elements(self) -> list[dict[str, Any]]:
        stats = compute_notification_stats(self._repo_statuses)
        elements: list[dict[str, Any]] = [
            self._build_overview_element(self._summary),
            {"tag": "hr"},
            self._build_stats_element(stats, total_commits=self._total_commits),
        ]

        failed_element = self._build_repo_list_element(
            title=_("Failed Repositories"),
            repos=stats.failed_repos,
        )
        if failed_element:
            elements.append(failed_element)

        skipped_element = self._build_repo_list_element(
            title=_("Skipped Repositories"),
            repos=stats.skipped_repos,
        )
        if skipped_element:
            elements.append(skipped_element)

        action_element = self._build_action_element(self._markpost_url)
        if action_element:
            elements.append(action_element)

        return elements

    def _build_overview_element(self, summary: str) -> dict[str, Any]:
        overview_title = _("Overview")
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{overview_title}**\n{summary}",
            },
        }

    def _build_stats_element(self, stats, total_commits: int) -> dict[str, Any]:
        return {
            "tag": "div",
            "fields": [
                self._build_stat_field(_("Total Repositories"), stats.total_repos),
                self._build_stat_field(_("Total Commits"), total_commits),
                self._build_stat_field(_("Successful"), stats.success_count),
                self._build_stat_field(_("Failed"), stats.failed_count),
            ],
        }

    def _build_stat_field(self, label: str, value: int) -> dict[str, Any]:
        return {
            "is_short": True,
            "text": {
                "tag": "lark_md",
                "content": f"**{label}**\n{value}",
            },
        }

    def _build_repo_list_element(
        self, title: str, repos: list[str]
    ) -> dict[str, Any] | None:
        if not repos:
            return None

        visible = repos[:5]
        content_lines = [f"- {name}" for name in visible]
        if len(repos) > len(visible):
            content_lines.append(f"- ... and {len(repos) - len(visible)} more")

        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n" + "\n".join(content_lines),
            },
        }

    def _build_action_element(self, markpost_url: str | None) -> dict[str, Any] | None:
        if not markpost_url:
            return None
        return {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": _("View Detailed Report")},
                    "type": "default",
                    "url": markpost_url,
                }
            ],
        }
