"""Notification module - Feishu webhook and email notifications."""

from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import NotificationChannelConfig, NotificationConfig
from .consts import TEMPLATE_EMAIL_NOTIFICATION
from .errors import ProgressException
from .i18n import gettext as _

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class NotificationStats:
    total_repos: int
    success_count: int
    failed_count: int
    skipped_count: int
    failed_repos: list[str]
    skipped_repos: list[str]


@dataclass(frozen=True, slots=True)
class NotificationMessage:
    title: str
    summary: str
    total_commits: int
    markpost_url: str | None = None
    repo_statuses: Mapping[str, str] | None = None

    def stats(self) -> NotificationStats:
        statuses = self.repo_statuses or {}
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


class NotificationChannel(Protocol):
    def send(self, message: NotificationMessage) -> None: ...


class FeishuNotification:
    """Send Feishu webhook notifications."""

    def __init__(self, webhook_url: str, timeout: int = 30):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send(self, message: NotificationMessage) -> None:
        card = self._build_card(message)
        self._post_card(card, title=message.title)

    def _build_card(self, message: NotificationMessage) -> dict[str, Any]:
        return {
            "msg_type": "interactive",
            "card": {
                "header": self._build_header(message.title),
                "elements": self._build_elements(message),
            },
        }

    def _build_header(self, title: str) -> dict[str, Any]:
        return {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        }

    def _build_elements(self, message: NotificationMessage) -> list[dict[str, Any]]:
        stats = message.stats()
        elements: list[dict[str, Any]] = [
            self._build_overview_element(message.summary),
            {"tag": "hr"},
            self._build_stats_element(stats, total_commits=message.total_commits),
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

        action_element = self._build_action_element(message.markpost_url)
        if action_element:
            elements.append(action_element)

        return elements

    def _build_overview_element(self, summary: str) -> dict[str, Any]:
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{_('Overview')}**\n{summary}",
            },
        }

    def _build_stats_element(self, stats: NotificationStats, total_commits: int) -> dict[str, Any]:
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

    def _build_repo_list_element(self, title: str, repos: list[str]) -> dict[str, Any] | None:
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

    def _post_card(self, card: dict[str, Any], title: str) -> None:
        try:
            logger.info(f"Sending Feishu notification: {title}")
            response = requests.post(self.webhook_url, json=card, timeout=self.timeout)
            response.raise_for_status()
            logger.info("Feishu notification sent successfully")
        except requests.RequestException as e:
            logger.error(f"Failed to send Feishu notification: {e}")
            raise ProgressException(f"Failed to send Feishu notification: {e}") from e


class EmailNotification:
    """Send email notifications."""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        recipient: list[str],
        starttls: bool = True,
        ssl: bool = False,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.from_addr = from_addr
        self.recipient = recipient
        self.starttls = starttls
        self.ssl = ssl

        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def send(self, message: NotificationMessage) -> None:
        html_content = self._render_html(message)
        mime_message = self._build_mime(subject=message.title, html_content=html_content)
        self._send_mime(mime_message, subject=message.title)

    def _render_html(self, message: NotificationMessage) -> str:
        stats = message.stats()
        template = self.jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        return template.render(
            subject=message.title,
            summary=message.summary,
            total_commits=message.total_commits,
            total_repos=stats.total_repos,
            success_count=stats.success_count,
            failed_count=stats.failed_count,
            skipped_count=stats.skipped_count,
            failed_repos=list(stats.failed_repos),
            skipped_repos=list(stats.skipped_repos),
            markpost_url=message.markpost_url,
            _=_,
        )

    def _build_mime(self, subject: str, html_content: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.recipient)
        msg.attach(MIMEText(html_content, "html", "utf-8"))
        return msg

    def _send_mime(self, mime_message: MIMEMultipart, subject: str) -> None:
        try:
            logger.info(f"Sending email notification: {subject}")
            server = self._create_server()
            try:
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(
                    self.from_addr,
                    self.recipient,
                    mime_message.as_string(),
                )
                logger.info("Email notification sent successfully")
            finally:
                server.quit()
        except smtplib.SMTPException as e:
            logger.error(f"Failed to send email notification: {e}")
            raise ProgressException(f"Failed to send email notification: {e}") from e

    def _create_server(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        if self.ssl:
            return smtplib.SMTP_SSL(self.host, self.port)
        if self.starttls:
            server = smtplib.SMTP(self.host, self.port)
            server.starttls()
            return server
        return smtplib.SMTP(self.host, self.port)


class NotificationManager:
    def __init__(self, channels: Sequence[NotificationChannel]):
        self._channels = list(channels)

    @classmethod
    def from_config(cls, notification_config: NotificationConfig) -> "NotificationManager":
        channels: list[NotificationChannel] = [
            cls._build_channel(channel_config)
            for channel_config in notification_config.channels
            if channel_config.enabled
        ]

        return cls(channels)

    @staticmethod
    def _build_channel(channel_config: NotificationChannelConfig) -> NotificationChannel:
        match channel_config.type:
            case "feishu":
                return FeishuNotification(
                    webhook_url=str(channel_config.webhook_url),
                    timeout=channel_config.timeout,
                )
            case "email":
                return EmailNotification(
                    host=channel_config.host,
                    port=channel_config.port,
                    user=channel_config.user,
                    password=channel_config.password,
                    from_addr=channel_config.from_addr,
                    recipient=list(channel_config.recipient),
                    starttls=channel_config.starttls,
                    ssl=channel_config.ssl,
                )
            case _:
                raise ProgressException(
                    f"Unknown notification channel type: {channel_config.type}"
                )

    def send(self, message: NotificationMessage) -> None:
        failures: list[Exception] = []
        for channel in self._channels:
            try:
                channel.send(message)
            except Exception as e:
                failures.append(e)

        if failures:
            reasons = "; ".join(str(e) for e in failures)
            raise ProgressException(f"Failed to send notifications: {reasons}")
