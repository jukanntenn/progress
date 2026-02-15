from __future__ import annotations

from .base import Message
from .console import ConsoleMessage, ConsoleProposalMessage
from .email import EmailMessage, EmailProposalMessage
from .feishu import FeishuMessage, FeishuProposalMessage

__all__ = [
    "Message",
    "ConsoleMessage",
    "ConsoleProposalMessage",
    "EmailMessage",
    "EmailProposalMessage",
    "FeishuMessage",
    "FeishuProposalMessage",
]
