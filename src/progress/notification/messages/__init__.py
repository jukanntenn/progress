from __future__ import annotations

from .base import Message
from .console import ConsoleMessage
from .email import EmailMessage
from .feishu import FeishuMessage

__all__ = ["Message", "ConsoleMessage", "EmailMessage", "FeishuMessage"]
