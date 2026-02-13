from __future__ import annotations

import smtplib
from unittest.mock import MagicMock, patch

import pytest

from progress.errors import ExternalServiceException
from progress.notification.channels.email import EmailChannel


def test_email_channel_send_success_with_starttls() -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
        starttls=True,
        ssl=False,
    )
    payload = "Subject: Test\n\n<html>Body</html>"

    with patch("smtplib.SMTP") as mock_smtp:
        server = MagicMock()
        mock_smtp.return_value = server

        channel.send(payload)

        mock_smtp.assert_called_once_with("smtp.example.com", 587)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("user@example.com", "pass")
        server.sendmail.assert_called_once()
        server.quit.assert_called_once()


def test_email_channel_send_success_with_ssl() -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=465,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
        starttls=False,
        ssl=True,
    )
    payload = "Subject: Test\n\n<html>Body</html>"

    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        server = MagicMock()
        mock_smtp_ssl.return_value = server

        channel.send(payload)

        mock_smtp_ssl.assert_called_once_with("smtp.example.com", 465)
        server.starttls.assert_not_called()


def test_email_channel_send_raises_on_smtp_error() -> None:
    channel = EmailChannel(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
        starttls=True,
        ssl=False,
    )
    payload = "Subject: Test\n\n<html>Body</html>"

    with patch("smtplib.SMTP") as mock_smtp:
        server = MagicMock()
        mock_smtp.return_value = server
        server.sendmail.side_effect = smtplib.SMTPException("SMTP error")

        with pytest.raises(ExternalServiceException, match="Email notification failed"):
            channel.send(payload)
