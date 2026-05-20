from __future__ import annotations

from ..errors import ProgressException
from .channels import ConsoleChannel, EmailChannel, FeishuChannel
from .config import NotificationChannelConfig
from .messages import (
    ConsoleMessage,
    ConsoleProposalMessage,
    EmailMessage,
    EmailProposalMessage,
    FeishuMessage,
    FeishuProposalMessage,
    Message,
)


def create_channel(
    config: NotificationChannelConfig,
) -> ConsoleChannel | FeishuChannel | EmailChannel:
    match config.type:
        case "console":
            return ConsoleChannel()
        case "feishu":
            return FeishuChannel(
                webhook_url=str(config.webhook_url),
                timeout=config.timeout,
            )
        case "email":
            return EmailChannel(
                host=config.host,
                port=config.port,
                user=config.user,
                password=config.password,
                from_addr=config.from_addr,
                recipient=list(config.recipient),
                starttls=config.starttls,
                ssl=config.ssl,
            )
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")


def create_message(
    config: NotificationChannelConfig,
    channel: ConsoleChannel | FeishuChannel | EmailChannel,
) -> Message:
    match config.type:
        case "console":
            return ConsoleMessage(channel)
        case "feishu":
            return FeishuMessage(channel)
        case "email":
            return EmailMessage(channel)
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")


def create_proposal_message(
    config: NotificationChannelConfig,
    channel: ConsoleChannel | FeishuChannel | EmailChannel,
) -> Message:
    match config.type:
        case "console":
            return ConsoleProposalMessage(channel)
        case "feishu":
            return FeishuProposalMessage(channel)
        case "email":
            return EmailProposalMessage(channel)
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")
