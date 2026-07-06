from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib
import pytest

from progress.errors import ExternalServiceException
from progress.notification.channels.email import EmailChannel


async def test_email_channel_send_success_with_starttls() -> None:
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

    with patch("progress.notification.channels.email.aiosmtplib.SMTP") as mock_smtp:
        server = MagicMock()
        server.connect = AsyncMock()
        server.login = AsyncMock()
        server.sendmail = AsyncMock()
        server.close = MagicMock()
        server.quit = AsyncMock()
        mock_smtp.return_value = server

        await channel.send(payload)

        mock_smtp.assert_called_once_with(
            hostname="smtp.example.com", port=587, use_tls=False, start_tls=True
        )
        server.connect.assert_awaited_once()
        server.login.assert_awaited_once_with("user@example.com", "pass")
        server.sendmail.assert_awaited_once()
        server.quit.assert_awaited_once()


async def test_email_channel_send_success_with_ssl() -> None:
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

    with patch("progress.notification.channels.email.aiosmtplib.SMTP") as mock_smtp:
        server = MagicMock()
        server.connect = AsyncMock()
        server.login = AsyncMock()
        server.sendmail = AsyncMock()
        server.close = MagicMock()
        server.quit = AsyncMock()
        mock_smtp.return_value = server

        await channel.send(payload)

        mock_smtp.assert_called_once_with(
            hostname="smtp.example.com", port=465, use_tls=True, start_tls=False
        )


async def test_email_channel_send_raises_on_smtp_error() -> None:
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

    with patch("progress.notification.channels.email.aiosmtplib.SMTP") as mock_smtp:
        server = MagicMock()
        server.connect = AsyncMock()
        server.login = AsyncMock()
        server.sendmail = AsyncMock(side_effect=aiosmtplib.SMTPException("SMTP error"))
        server.close = MagicMock()
        server.quit = AsyncMock()
        mock_smtp.return_value = server

        with pytest.raises(ExternalServiceException, match="Email notification failed"):
            await channel.send(payload)
