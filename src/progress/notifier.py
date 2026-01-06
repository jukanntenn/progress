"""Notification module - Feishu webhook and email notifications."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional

import requests
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .consts import TEMPLATE_EMAIL_NOTIFICATION
from .errors import ProgressException

logger = logging.getLogger(__name__)


class FeishuNotifier:
    """Send Feishu webhook notifications."""

    def __init__(self, webhook_url: str, timeout: int = 30):
        self.webhook_url = webhook_url
        self.timeout = timeout

    def send_notification(
        self,
        repo_name: str,
        commit_count: int,
        summary: str,
        markpost_url: Optional[str] = None,
    ):
        """Send Feishu notification."""
        elements = [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Change Summary**\n{summary}",
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
                            "content": f"**Commits**\n{commit_count}",
                        },
                    },
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**Repository**\n{repo_name}",
                        },
                    },
                ],
            },
        ]

        if markpost_url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {
                                "tag": "plain_text",
                                "content": "View Detailed Report",
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
                        "content": f"Code Change Notification - {repo_name}",
                    },
                    "template": "blue",
                },
                "elements": elements,
            },
        }

        try:
            logger.info(f"Sending Feishu notification: {repo_name}")
            response = requests.post(self.webhook_url, json=card, timeout=self.timeout)
            response.raise_for_status()
            logger.info(f"Feishu notification sent successfully: {repo_name}")
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
        repo_name: str,
        commit_count: int,
        summary: str,
        markpost_url: Optional[str] = None,
    ):
        """Send email notification."""
        subject = f"Code Change Notification - {repo_name}"

        template = self.jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        html_content = template.render(
            subject=subject,
            summary=summary,
            commit_count=commit_count,
            repo_name=repo_name,
            markpost_url=markpost_url,
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(self.recipient)
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            logger.info(f"Sending email notification: {repo_name}")
            server = self._create_smtp_server()
            try:
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.from_addr, self.recipient, msg.as_string())
                logger.info(f"Email notification sent successfully: {repo_name}")
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
