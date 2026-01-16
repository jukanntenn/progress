"""Notification module - Feishu webhook and email notifications."""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .consts import TEMPLATE_EMAIL_NOTIFICATION
from .errors import ProgressException
from .i18n import gettext as _

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """Send Feishu webhook notifications."""

    def __init__(self, webhook_url: str, timeout: int = 30):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send_notification(
        self,
        title: str,
        total_commits: int,
        summary: str,
        markpost_url: Optional[str] = None,
        repo_statuses: dict[str, str] | None = None,
        reports: list | None = None,
    ):
        """Send Feishu notification with inspection overview.

        Args:
            title: Card title
            total_commits: Total commit count
            summary: Summary text
            markpost_url: Markpost URL
            repo_statuses: Dict mapping repo names to status
            reports: List of RepositoryReport objects
        """
        total_repos = len(repo_statuses or {})
        success_count = sum(1 for s in (repo_statuses or {}).values() if s == "success")
        failed_count = sum(1 for s in (repo_statuses or {}).values() if s == "failed")
        skipped_count = sum(1 for s in (repo_statuses or {}).values() if s == "skipped")

        failed_repos = [
            name for name, status in (repo_statuses or {}).items() if status == "failed"
        ]
        skipped_repos = [
            name
            for name, status in (repo_statuses or {}).items()
            if status == "skipped"
        ]

        overview_title = _("Overview")
        failed = _("Failed")
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**{overview_title}**\n{summary}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{_('Total Repositories')}**\n{total_repos}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{_('Total Commits')}**\n{total_commits}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{_('Successful')}**\n{success_count}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{failed}**\n{failed_count}",
                        },
                    },
                ],
            },
        ]

        if failed_repos:
            failed_text = (
                "**"
                + _("Failed Repositories")
                + "**\n"
                + "\n".join(f"- {name}" for name in failed_repos[:5])
            )
            if len(failed_repos) > 5:
                failed_text += f"\n- ... and {len(failed_repos) - 5} more"
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": failed_text},
                }
            )

        if skipped_repos:
            skipped_text = (
                "**"
                + _("Skipped Repositories")
                + "**\n"
                + "\n".join(f"- {name}" for name in skipped_repos[:5])
            )
            if len(skipped_repos) > 5:
                skipped_text += f"\n- ... and {len(skipped_repos) - 5} more"
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": skipped_text},
                }
            )

        if markpost_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": _("View Detailed Report"),
                            },
                            "type": "default",
                            "url": markpost_url,
                        }
                    ],
                }
            )

        card = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title,
                    },
                    "template": "blue",
                },
                "elements": elements,
            },
        }

        try:
            logger.info(f"Sending Feishu notification: {title}")
            response = requests.post(self.webhook_url, json=card, timeout=self.timeout)
            response.raise_for_status()
            logger.info("Feishu notification sent successfully")
        except requests.RequestException as e:
            logger.error(f"Failed to send Feishu notification: {e}")
            raise ProgressException(f"Failed to send Feishu notification: {e}") from e


class EmailNotifier:
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

    def send_notification(
        self,
        subject: str,
        total_commits: int,
        summary: str,
        markpost_url: Optional[str] = None,
        repo_statuses: dict[str, str] | None = None,
        reports: list | None = None,
        _=lambda x: x,
    ):
        """Send email notification with i18n support.

        Args:
            subject: Email subject
            total_commits: Total commit count
            summary: Summary text
            markpost_url: Markpost URL
            repo_statuses: Dict mapping repo names to status
            reports: List of RepositoryReport objects
            _: gettext function
        """
        total_repos = len(repo_statuses or {})
        success_count = sum(1 for s in (repo_statuses or {}).values() if s == "success")
        failed_count = sum(1 for s in (repo_statuses or {}).values() if s == "failed")
        skipped_count = sum(1 for s in (repo_statuses or {}).values() if s == "skipped")

        failed_repos = [
            name for name, status in (repo_statuses or {}).items() if status == "failed"
        ]
        skipped_repos = [
            name
            for name, status in (repo_statuses or {}).items()
            if status == "skipped"
        ]

        template = self.jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        html_content = template.render(
            subject=subject,
            summary=summary,
            total_commits=total_commits,
            total_repos=total_repos,
            success_count=success_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
            failed_repos=failed_repos,
            skipped_repos=skipped_repos,
            markpost_url=markpost_url,
            _=_,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.recipient)
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            logger.info(f"Sending email notification: {subject}")
            server = self._create_smtp_server()
            try:
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, self.recipient, msg.as_string())
                logger.info("Email notification sent successfully")
            finally:
                server.quit()
        except smtplib.SMTPException as e:
            logger.error(f"Failed to send email notification: {e}")
            raise ProgressException(f"Failed to send email notification: {e}") from e

    def _create_smtp_server(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        """Create SMTP server connection."""
        if self.ssl:
            return smtplib.SMTP_SSL(self.host, self.port)
        if self.starttls:
            server = smtplib.SMTP(self.host, self.port)
            server.starttls()
            return server
        return smtplib.SMTP(self.host, self.port)
