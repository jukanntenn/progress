from __future__ import annotations

from typing import Any

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
    **kwargs: Any,
) -> Message:
    match config.type:
        case "console":
            return ConsoleMessage(
                channel,
                title=kwargs.get("title", ""),
                summary=kwargs.get("summary", ""),
                total_commits=kwargs.get("total_commits", 0),
                markpost_url=kwargs.get("markpost_url"),
                repo_statuses=kwargs.get("repo_statuses"),
                notification_type=kwargs.get("notification_type", "repo_update"),
                changelog_entries=kwargs.get("changelog_entries"),
                batch_index=kwargs.get("batch_index"),
                total_batches=kwargs.get("total_batches"),
            )
        case "feishu":
            return FeishuMessage(
                channel,
                title=kwargs.get("title", ""),
                summary=kwargs.get("summary", ""),
                total_commits=kwargs.get("total_commits", 0),
                markpost_url=kwargs.get("markpost_url"),
                repo_statuses=kwargs.get("repo_statuses"),
                notification_type=kwargs.get("notification_type", "repo_update"),
                changelog_entries=kwargs.get("changelog_entries"),
                batch_index=kwargs.get("batch_index"),
                total_batches=kwargs.get("total_batches"),
            )
        case "email":
            return EmailMessage(
                channel,
                title=kwargs.get("title", ""),
                summary=kwargs.get("summary", ""),
                total_commits=kwargs.get("total_commits", 0),
                markpost_url=kwargs.get("markpost_url"),
                repo_statuses=kwargs.get("repo_statuses"),
                notification_type=kwargs.get("notification_type", "repo_update"),
                changelog_entries=kwargs.get("changelog_entries"),
                batch_index=kwargs.get("batch_index"),
                total_batches=kwargs.get("total_batches"),
            )
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")


def create_proposal_message(
    config: NotificationChannelConfig,
    channel: ConsoleChannel | FeishuChannel | EmailChannel,
    **kwargs: Any,
) -> Message:
    match config.type:
        case "console":
            return ConsoleProposalMessage(
                channel,
                title=kwargs.get("title", ""),
                markpost_url=kwargs.get("markpost_url"),
                filenames=kwargs.get("filenames"),
                more_count=kwargs.get("more_count", 0),
            )
        case "feishu":
            return FeishuProposalMessage(
                channel,
                title=kwargs.get("title", ""),
                markpost_url=kwargs.get("markpost_url"),
                filenames=kwargs.get("filenames"),
                more_count=kwargs.get("more_count", 0),
            )
        case "email":
            return EmailProposalMessage(
                channel,
                title=kwargs.get("title", ""),
                markpost_url=kwargs.get("markpost_url"),
                filenames=kwargs.get("filenames"),
                more_count=kwargs.get("more_count", 0),
            )
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")
