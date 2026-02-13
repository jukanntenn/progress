from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from ...errors import ExternalServiceException

logger = logging.getLogger(__name__)


class EmailChannel:
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        from_addr: str,
        recipient: list[str],
        starttls: bool = False,
        ssl: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_addr = from_addr
        self._recipient = list(recipient)
        self._starttls = starttls
        self._ssl = ssl

    def send(self, payload: str) -> None:
        subject, html_content = self._parse_payload(payload)
        mime_message = self._build_mime(subject=subject, html_content=html_content)
        self._send_mime(mime_message)

    def _parse_payload(self, payload: str) -> tuple[str, str]:
        if payload.startswith("Subject:"):
            head, _, rest = payload.partition("\n")
            subject = head.removeprefix("Subject:").strip()
            html_content = rest.lstrip("\n")
            return subject, html_content
        return "", payload

    def _build_mime(self, subject: str, html_content: str) -> MIMEMultipart:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._recipient)
        msg.attach(MIMEText(html_content, "html", "utf-8"))
        return msg

    def _send_mime(self, mime_message: MIMEMultipart) -> None:
        try:
            server = self._create_server()
            try:
                if self._user and self._password:
                    server.login(self._user, self._password)
                server.sendmail(
                    self._from_addr,
                    self._recipient,
                    mime_message.as_string(),
                )
            finally:
                server.quit()
        except (smtplib.SMTPException, OSError) as e:
            logger.warning("Failed to send email notification: %s", e)
            raise ExternalServiceException(f"Email notification failed: {e}") from e

    def _create_server(self) -> smtplib.SMTP | smtplib.SMTP_SSL:
        if self._ssl:
            return smtplib.SMTP_SSL(self._host, self._port)
        if self._starttls:
            server = smtplib.SMTP(self._host, self._port)
            server.starttls()
            return server
        return smtplib.SMTP(self._host, self._port)
