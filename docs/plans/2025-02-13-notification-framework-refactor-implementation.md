# Notification Framework Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor the notification system to adopt protocol-based architecture separating message formatting from transport delivery, add Console channel, while preserving all existing functionality.

**Architecture:** Three-layer protocol design - Channel protocol defines `send(payload: str) -> None` contract, Message classes handle formatting and business logic, Channel implementations handle pure transport. Factory functions create instances from Pydantic config.

**Tech Stack:** Python 3.12+, Pydantic, Pydantic Settings, pytest, requests, smtplib, Jinja2

---

## Task 1: Project Structure Setup

**Files:**
- Create: `src/progress/notification/__init__.py`
- Create: `src/progress/notification/base.py`
- Create: `src/progress/notification/channels/__init__.py`
- Create: `src/progress/notification/messages/__init__.py`
- Create: `src/progress/notification/utils.py`

**Step 1: Create base channel protocol**

Create `src/progress/notification/base.py`:

```python
from typing import Protocol


class Channel(Protocol):
    def send(self, payload: str) -> None: ...
```

**Step 2: Create empty channel module init**

Create `src/progress/notification/channels/__init__.py`:

```python
from .console import ConsoleChannel
from .email import EmailChannel
from .feishu import FeishuChannel

__all__ = ["Channel", "ConsoleChannel", "EmailChannel", "FeishuChannel"]
```

**Step 3: Create empty message module init**

Create `src/progress/notification/messages/__init__.py`:

```python
from .base import Message
from .console import ConsoleMessage
from .email import EmailMessage
from .feishu import FeishuMessage

__all__ = ["Message", "ConsoleMessage", "EmailMessage", "FeishuMessage"]
```

**Step 4: Create utilities placeholder**

Create `src/progress/notification/utils.py`:

```python
def format_text(title: str, urls: list[str]) -> str:
    lines = [title]
    lines.extend(urls)
    return "\n".join(lines)
```

**Step 5: Create notification package init**

Create `src/progress/notification/__init__.py`:

```python
from .base import Channel
from .channels import ConsoleChannel, EmailChannel, FeishuChannel
from .messages import ConsoleMessage, EmailMessage, FeishuMessage
from .utils import format_text

__all__ = [
    "Channel",
    "ConsoleChannel",
    "EmailChannel",
    "FeishuChannel",
    "ConsoleMessage",
    "EmailMessage",
    "FeishuMessage",
    "format_text",
]
```

**Step 6: Commit**

```bash
git add src/progress/notification/
git commit -m "feat(notification): add package structure and base protocol
- Add Channel protocol
- Add module structure for channels and messages
- Add format_text utility
"
```

---

## Task 2: Base Message Class

**Files:**
- Create: `src/progress/notification/messages/base.py`
- Create: `tests/notification/test_base_message.py`

**Step 1: Write failing test for Message.send()**

Create `tests/notification/test_base_message.py`:

```python
import logging
from unittest.mock import Mock

import pytest

from progress.notification.base import Channel
from progress.notification.messages.base import Message

logger = logging.getLogger(__name__)


def test_message_send_calls_channel():
    mock_channel = Mock(spec=Channel)

    class TestMessage(Message):
        def __init__(self, channel: Channel):
            super().__init__(channel)
            self._test_payload = "test payload"

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return self._test_payload

    message = TestMessage(mock_channel)
    result = message.send()

    assert result is True
    mock_channel.send.assert_called_once_with("test payload")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notification/test_base_message.py::test_message_send_calls_channel -v`
Expected: FAIL with "No module named 'progress.notification.messages.base'"

**Step 3: Implement base Message class**

Create `src/progress/notification/messages/base.py`:

```python
import logging
from abc import ABC, abstractmethod

from ..base import Channel

logger = logging.getLogger(__name__)


class Message(ABC):
    def __init__(self, channel: Channel) -> None:
        self._channel = channel

    @abstractmethod
    def get_channel(self) -> Channel: ...

    @abstractmethod
    def get_payload(self) -> str: ...

    def send(self, fail_silently: bool = True) -> bool:
        try:
            self.get_channel().send(self.get_payload())
            return True
        except Exception as e:
            logger.warning("Channel failed: %s", e)
            if not fail_silently:
                raise
            return False
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/notification/test_base_message.py::test_message_send_calls_channel -v`
Expected: PASS

**Step 5: Write failing test for error handling**

Add to `tests/notification/test_base_message.py`:

```python
def test_message_send_returns_false_on_error():
    mock_channel = Mock(spec=Channel)
    mock_channel.send.side_effect = Exception("Test error")

    class TestMessage(Message):
        def __init__(self, channel: Channel):
            super().__init__(channel)

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return "test payload"

    message = TestMessage(mock_channel)
    result = message.send(fail_silently=True)

    assert result is False
```

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/notification/test_base_message.py::test_message_send_returns_false_on_error -v`
Expected: PASS

**Step 7: Write failing test for exception when not fail_silently**

Add to `tests/notification/test_base_message.py`:

```python
def test_message_send_raises_on_error_when_not_fail_silently():
    mock_channel = Mock(spec=Channel)
    mock_channel.send.side_effect = Exception("Test error")

    class TestMessage(Message):
        def __init__(self, channel: Channel):
            super().__init__(channel)

        def get_channel(self) -> Channel:
            return self._channel

        def get_payload(self) -> str:
            return "test payload"

    message = TestMessage(mock_channel)

    with pytest.raises(Exception, match="Test error"):
        message.send(fail_silently=False)
```

**Step 8: Run all message tests**

Run: `uv run pytest tests/notification/test_base_message.py -v`
Expected: ALL PASS

**Step 9: Commit**

```bash
git add src/progress/notification/messages/base.py tests/notification/test_base_message.py
git commit -m "feat(notification): add Message base class with error handling
- Add abstract Message class
- Implement send() with fail_silently flag
- Add tests for success, failure, and error propagation
"
```

---

## Task 3: Console Channel and Message

**Files:**
- Create: `src/progress/notification/channels/console.py`
- Create: `src/progress/notification/messages/console.py`
- Create: `tests/notification/channels/test_console_channel.py`
- Create: `tests/notification/messages/test_console_message.py`

**Step 1: Write failing test for ConsoleChannel**

Create `tests/notification/channels/test_console_channel.py`:

```python
import logging
from io import StringIO

from progress.notification.channels.console import ConsoleChannel

logger = logging.getLogger(__name__)


def test_console_channel_send_prints_payload():
    channel = ConsoleChannel()
    payload = "Test notification"

    with StringIO() as buffer:
        import sys
        old_stdout = sys.stdout
        sys.stdout = buffer

        try:
            channel.send(payload)
            output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        assert payload in output
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notification/channels/test_console_channel.py::test_console_channel_send_prints_payload -v`
Expected: FAIL with "No module named 'progress.notification.channels.console'"

**Step 3: Implement ConsoleChannel**

Create `src/progress/notification/channels/console.py`:

```python
import logging

logger = logging.getLogger(__name__)


class ConsoleChannel:
    def send(self, payload: str) -> None:
        logger.debug("Sending console notification")
        print(payload)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/notification/channels/test_console_channel.py::test_console_channel_send_prints_payload -v`
Expected: PASS

**Step 5: Write failing test for ConsoleMessage**

Create `tests/notification/messages/test_console_message.py`:

```python
from progress.notification.channels.console import ConsoleChannel
from progress.notification.messages.console import ConsoleMessage


def test_console_message_get_payload_returns_text():
    channel = ConsoleChannel()
    message = ConsoleMessage(channel, "Test notification text")

    payload = message.get_payload()

    assert payload == "Test notification text"


def test_console_message_get_channel_returns_channel():
    channel = ConsoleChannel()
    message = ConsoleMessage(channel, "Test")

    returned_channel = message.get_channel()

    assert returned_channel is channel
```

**Step 6: Run tests to verify they fail**

Run: `uv run pytest tests/notification/messages/test_console_message.py -v`
Expected: FAIL with "No module named 'progress.notification.messages.console'"

**Step 7: Implement ConsoleMessage**

Create `src/progress/notification/messages/console.py`:

```python
import logging

from ..channels.console import ConsoleChannel
from .base import Message

logger = logging.getLogger(__name__)


class ConsoleMessage(Message):
    def __init__(self, channel: ConsoleChannel, text: str) -> None:
        super().__init__(channel)
        self._text = text

    def get_channel(self) -> ConsoleChannel:
        return self._channel

    def get_payload(self) -> str:
        return self._text
```

**Step 8: Run all console tests**

Run: `uv run pytest tests/notification/channels/test_console_channel.py tests/notification/messages/test_console_message.py -v`
Expected: ALL PASS

**Step 9: Update channel imports**

Update `src/progress/notification/channels/__init__.py`:

```python
from .console import ConsoleChannel

__all__ = ["ConsoleChannel"]
```

**Step 10: Update message imports**

Update `src/progress/notification/messages/__init__.py`:

```python
from .base import Message
from .console import ConsoleMessage

__all__ = ["Message", "ConsoleMessage"]
```

**Step 11: Run all notification tests**

Run: `uv run pytest tests/notification/ -v`
Expected: ALL PASS

**Step 12: Commit**

```bash
git add src/progress/notification/channels/ src/progress/notification/messages/ tests/notification/
git commit -m "feat(notification): add console channel and message
- Add ConsoleChannel for stdout delivery
- Add ConsoleMessage for text notifications
- Add tests for console channel and message
"
```

---

## Task 4: Feishu Channel and Message

**Files:**
- Create: `src/progress/notification/channels/feishu.py`
- Create: `src/progress/notification/messages/feishu.py`
- Create: `tests/notification/channels/test_feishu_channel.py`
- Create: `tests/notification/messages/test_feishu_message.py`
- Modify: `src/progress/errors.py` (add ExternalServiceException if not exists)

**Step 1: Add external service exception**

Check `src/progress/errors.py` for ExternalServiceException. If not present, add:

```python
class ExternalServiceException(ProgressException):
    """Raised when an external service call fails."""
```

**Step 2: Write failing test for FeishuChannel success**

Create `tests/notification/channels/test_feishu_channel.py`:

```python
from unittest.mock import Mock, patch

import pytest
import requests

from progress.errors import ExternalServiceException
from progress.notification.channels.feishu import FeishuChannel


def test_feishu_channel_send_success():
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"msg_type": "interactive", "card": {...}}'

    with patch("requests.post") as mock_post:
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response

        channel.send(payload)

        mock_post.assert_called_once_with(
            url="https://example.com/webhook",
            json=payload,
            timeout=30
        )
        mock_response.raise_for_status.assert_called_once()
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/notification/channels/test_feishu_channel.py::test_feishu_channel_send_success -v`
Expected: FAIL with "No module named 'progress.notification.channels.feishu'"

**Step 4: Implement FeishuChannel**

Create `src/progress/notification/channels/feishu.py`:

```python
import json
import logging

import requests

from progress.errors import ExternalServiceException

logger = logging.getLogger(__name__)


class FeishuChannel:
    def __init__(self, webhook_url: str, timeout: int) -> None:
        self._webhook_url = webhook_url
        self._timeout = timeout

    def send(self, payload: str) -> None:
        logger.info("Sending Feishu notification")
        payload_data = json.loads(payload)
        try:
            resp = requests.post(
                url=self._webhook_url, json=payload_data, timeout=self._timeout
            )
            resp.raise_for_status()
            logger.info("Feishu notification sent successfully")
        except requests.RequestException as e:
            logger.warning("Failed to send Feishu notification: %s", e)
            raise ExternalServiceException(f"Feishu notification failed: {e}") from e
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/notification/channels/test_feishu_channel.py::test_feishu_channel_send_success -v`
Expected: PASS

**Step 6: Write failing test for webhook error handling**

Add to `tests/notification/channels/test_feishu_channel.py`:

```python
def test_feishu_channel_send_raises_on_request_error():
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    payload = '{"text": "test"}'

    with patch("requests.post") as mock_post:
        mock_post.side_effect = requests.RequestException("Connection error")

        with pytest.raises(ExternalServiceException, match="Feishu notification failed"):
            channel.send(payload)
```

**Step 7: Run test to verify it passes**

Run: `uv run pytest tests/notification/channels/test_feishu_channel.py::test_feishu_channel_send_raises_on_request_error -v`
Expected: PASS

**Step 8: Write failing test for FeishuMessage card structure**

Create `tests/notification/messages/test_feishu_message.py`:

```python
import json

from progress.notification.channels.feishu import FeishuChannel
from progress.notification.messages.feishu import FeishuMessage


def test_feishu_message_get_payload_returns_json_card():
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    message = FeishuMessage(
        channel,
        title="Test Title",
        summary="Test summary",
        total_commits=10,
        repo_statuses={"repo1": "success", "repo2": "failed"},
        markpost_url="https://example.com/report",
        batch_index=0,
        total_batches=2,
    )

    payload = message.get_payload()
    parsed = json.loads(payload)

    assert parsed["msg_type"] == "interactive"
    assert "card" in parsed
    assert parsed["card"]["header"]["title"]["content"] == "Test Title (1/2)"


def test_feishu_message_get_channel_returns_channel():
    channel = FeishuChannel(webhook_url="https://example.com/webhook", timeout=30)
    message = FeishuMessage(
        channel,
        title="Test",
        summary="Summary",
        total_commits=5,
    )

    returned_channel = message.get_channel()

    assert returned_channel is channel
```

**Step 9: Run tests to verify they fail**

Run: `uv run pytest tests/notification/messages/test_feishu_message.py -v`
Expected: FAIL with "No module named 'progress.notification.messages.feishu'"

**Step 10: Implement FeishuMessage**

Create `src/progress/notification/messages/feishu.py`:

```python
import json
import logging
from typing import Any

from ..channels.feishu import FeishuChannel
from .base import Message

logger = logging.getLogger(__name__)


class FeishuMessage(Message):
    def __init__(
        self,
        channel: FeishuChannel,
        title: str,
        summary: str,
        total_commits: int,
        repo_statuses: dict[str, str] | None = None,
        markpost_url: str | None = None,
        batch_index: int | None = None,
        total_batches: int | None = None,
    ) -> None:
        super().__init__(channel)
        self._title = title
        self._summary = summary
        self._total_commits = total_commits
        self._repo_statuses = repo_statuses or {}
        self._markpost_url = markpost_url
        self._batch_index = batch_index
        self._total_batches = total_batches
        logger.debug("Preparing Feishu notification: %s", title)

    def get_channel(self) -> FeishuChannel:
        return self._channel

    def get_payload(self) -> str:
        title_with_batch = self._add_batch_indicator(
            self._title, self._batch_index, self._total_batches
        )
        card = {
            "msg_type": "interactive",
            "card": {
                "header": self._build_header(title_with_batch),
                "elements": self._build_elements(),
            },
        }
        return json.dumps(card, ensure_ascii=False)

    def _add_batch_indicator(
        self, title: str, batch_index: int | None, total_batches: int | None
    ) -> str:
        if batch_index is not None and total_batches is not None and total_batches > 1:
            return f"{title} ({batch_index + 1}/{total_batches})"
        return title

    def _build_header(self, title: str) -> dict[str, Any]:
        return {
            "title": {"tag": "plain_text", "content": title},
            "template": "blue",
        }

    def _build_elements(self) -> list[dict[str, Any]]:
        elements: list[dict[str, Any]] = [
            self._build_overview_element(),
            {"tag": "hr"},
            self._build_stats_element(),
        ]

        failed_repos = [r for r, s in self._repo_statuses.items() if s == "failed"]
        if failed_repos:
            elements.append(self._build_repo_list_element("Failed Repositories", failed_repos))

        skipped_repos = [r for r, s in self._repo_statuses.items() if s == "skipped"]
        if skipped_repos:
            elements.append(self._build_repo_list_element("Skipped Repositories", skipped_repos))

        if self._markpost_url:
            elements.append(self._build_action_element())

        return elements

    def _build_overview_element(self) -> dict[str, Any]:
        return {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Overview**\n{self._summary}",
            },
        }

    def _build_stats_element(self) -> dict[str, Any]:
        success_count = sum(1 for s in self._repo_statuses.values() if s == "success")
        failed_count = sum(1 for s in self._repo_statuses.values() if s == "failed")
        total_repos = len(self._repo_statuses)

        return {
            "tag": "div",
            "fields": [
                self._build_stat_field("Total Repositories", total_repos),
                self._build_stat_field("Total Commits", self._total_commits),
                self._build_stat_field("Successful", success_count),
                self._build_stat_field("Failed", failed_count),
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

    def _build_repo_list_element(self, title: str, repos: list[str]) -> dict[str, Any]:
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

    def _build_action_element(self) -> dict[str, Any]:
        return {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "View Detailed Report"},
                    "type": "default",
                    "url": self._markpost_url,
                }
            ],
        }
```

**Step 11: Run all feishu tests**

Run: `uv run pytest tests/notification/channels/test_feishu_channel.py tests/notification/messages/test_feishu_message.py -v`
Expected: ALL PASS

**Step 12: Update imports**

Update `src/progress/notification/channels/__init__.py`:

```python
from .console import ConsoleChannel
from .feishu import FeishuChannel

__all__ = ["ConsoleChannel", "FeishuChannel"]
```

Update `src/progress/notification/messages/__init__.py`:

```python
from .base import Message
from .console import ConsoleMessage
from .feishu import FeishuMessage

__all__ = ["Message", "ConsoleMessage", "FeishuMessage"]
```

Update `src/progress/notification/__init__.py`:

```python
from .base import Channel
from .channels import ConsoleChannel, FeishuChannel
from .messages import ConsoleMessage, FeishuMessage
from .utils import format_text

__all__ = [
    "Channel",
    "ConsoleChannel",
    "FeishuChannel",
    "ConsoleMessage",
    "FeishuMessage",
    "format_text",
]
```

**Step 13: Commit**

```bash
git add src/progress/notification/ tests/notification/ src/progress/errors.py
git commit -m "feat(notification): add feishu channel and message
- Add FeishuChannel for HTTP POST delivery
- Add FeishuMessage for JSON card formatting
- Preserve existing card structure (header, stats, repo lists, actions)
- Add ExternalServiceException for transport errors
- Add tests for feishu channel success and error cases
"
```

---

## Task 5: Email Channel and Message

**Files:**
- Create: `src/progress/notification/channels/email.py`
- Create: `src/progress/notification/messages/email.py`
- Create: `tests/notification/channels/test_email_channel.py`
- Create: `tests/notification/messages/test_email_message.py`

**Step 1: Write failing test for EmailChannel success**

Create `tests/notification/channels/test_email_channel.py`:

```python
from unittest.mock import Mock, patch, MagicMock

import pytest

from progress.notification.channels.email import EmailChannel


def test_email_channel_send_success():
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="pass",
        from_address="from@example.com",
        to_addresses=["to@example.com"],
        use_tls=True,
    )
    payload = "Subject: Test\n\nTest body"

    with patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp

        channel.send(payload)

        mock_smtp_class.assert_called_once_with("smtp.example.com", 587)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@example.com", "pass")
        mock_smtp.send_message.assert_called_once()
        mock_smtp.quit.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notification/channels/test_email_channel.py::test_email_channel_send_success -v`
Expected: FAIL with "No module named 'progress.notification.channels.email'"

**Step 3: Implement EmailChannel**

Create `src/progress/notification/channels/email.py`:

```python
import logging
import smtplib

from email.message import EmailMessage

from progress.errors import ExternalServiceException

logger = logging.getLogger(__name__)


class EmailChannel:
    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_address: str,
        to_addresses: list[str],
        use_tls: bool = True,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_address = from_address
        self._to_addresses = to_addresses
        self._use_tls = use_tls

    def send(self, payload: str) -> None:
        logger.info("Sending email notification")
        msg = EmailMessage()
        msg.set_content(payload)

        lines = payload.split("\n", 1)
        if lines[0].startswith("Subject:"):
            subject = lines[0].replace("Subject:", "").strip()
            body = lines[1] if len(lines) > 1 else ""
            msg.set_content(body)
            msg["Subject"] = subject
        else:
            msg.set_content(payload)

        msg["From"] = self._from_address
        msg["To"] = ", ".join(self._to_addresses)

        try:
            with smtplib.SMTP(self._smtp_host, self._smtp_port) as server:
                if self._use_tls:
                    server.starttls()
                server.login(self._username, self._password)
                server.send_message(msg)
            logger.info("Email notification sent successfully")
        except (smtplib.SMTPException, OSError) as e:
            logger.warning("Failed to send email notification: %s", e)
            raise ExternalServiceException(f"Email notification failed: {e}") from e
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/notification/channels/test_email_channel.py::test_email_channel_send_success -v`
Expected: PASS

**Step 5: Write failing test for email error handling**

Add to `tests/notification/channels/test_email_channel.py`:

```python
def test_email_channel_send_raises_on_smtp_error():
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="pass",
        from_address="from@example.com",
        to_addresses=["to@example.com"],
        use_tls=True,
    )
    payload = "Subject: Test\n\nTest body"

    with patch("smtplib.SMTP") as mock_smtp_class:
        mock_smtp = MagicMock()
        mock_smtp_class.return_value = mock_smtp
        mock_smtp.send_message.side_effect = smtplib.SMTPException("SMTP error")

        with pytest.raises(ExternalServiceException, match="Email notification failed"):
            channel.send(payload)
```

**Step 6: Run test to verify it passes**

Run: `uv run pytest tests/notification/channels/test_email_channel.py::test_email_channel_send_raises_on_smtp_error -v`
Expected: PASS

**Step 7: Write failing test for EmailMessage**

Create `tests/notification/messages/test_email_message.py`:

```python
from unittest.mock import patch, MagicMock

from progress.notification.channels.email import EmailChannel
from progress.notification.messages.email import EmailMessage


def test_email_message_get_payload_includes_subject_and_body():
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="pass",
        from_address="from@example.com",
        to_addresses=["to@example.com"],
    )
    message = EmailMessage(
        channel,
        subject="Test Subject",
        body="Test body",
        template_data={},
    )

    with patch("progress.notification.messages.email.Environment") as mock_env:
        mock_jinja = MagicMock()
        mock_env.return_value = mock_jinja
        mock_template = MagicMock()
        mock_jinja.get_template.return_value = mock_template
        mock_template.render.return_value = "<html>Rendered content</html>"

        payload = message.get_payload()

        assert "Subject: Test Subject" in payload


def test_email_message_get_channel_returns_channel():
    channel = EmailChannel(
        smtp_host="smtp.example.com",
        smtp_port=587,
        username="user@example.com",
        password="pass",
        from_address="from@example.com",
        to_addresses=["to@example.com"],
    )
    message = EmailMessage(
        channel,
        subject="Test",
        body="Body",
        template_data={},
    )

    returned_channel = message.get_channel()

    assert returned_channel is channel
```

**Step 8: Run tests to verify they fail**

Run: `uv run pytest tests/notification/messages/test_email_message.py -v`
Expected: FAIL with "No module named 'progress.notification.messages.email'"

**Step 9: Implement EmailMessage**

Create `src/progress/notification/messages/email.py`:

```python
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..channels.email import EmailChannel
from .base import Message

logger = logging.getLogger(__name__)


class EmailMessage(Message):
    def __init__(
        self,
        channel: EmailChannel,
        subject: str,
        body: str,
        template_data: dict,
    ) -> None:
        super().__init__(channel)
        self._subject = subject
        self._body = body
        self._template_data = template_data

        template_dir = Path(__file__).parent.parent.parent / "templates"
        self._jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.debug("Preparing email notification: %s", subject)

    def get_channel(self) -> EmailChannel:
        return self._channel

    def get_payload(self) -> str:
        from progress.i18n import gettext as _

        self._jinja_env.globals["_"] = _

        from progress.consts import TEMPLATE_EMAIL_NOTIFICATION

        template = self._jinja_env.get_template(TEMPLATE_EMAIL_NOTIFICATION)
        html_content = template.render(**self._template_data)

        return f"Subject: {self._subject}\n\n{html_content}"
```

**Step 10: Run all email tests**

Run: `uv run pytest tests/notification/channels/test_email_channel.py tests/notification/messages/test_email_message.py -v`
Expected: ALL PASS

**Step 11: Update all imports**

Update `src/progress/notification/channels/__init__.py`:

```python
from .console import ConsoleChannel
from .email import EmailChannel
from .feishu import FeishuChannel

__all__ = ["ConsoleChannel", "EmailChannel", "FeishuChannel"]
```

Update `src/progress/notification/messages/__init__.py`:

```python
from .base import Message
from .console import ConsoleMessage
from .email import EmailMessage
from .feishu import FeishuMessage

__all__ = ["Message", "ConsoleMessage", "EmailMessage", "FeishuMessage"]
```

Update `src/progress/notification/__init__.py`:

```python
from .base import Channel
from .channels import ConsoleChannel, EmailChannel, FeishuChannel
from .messages import ConsoleMessage, EmailMessage, FeishuMessage
from .utils import format_text

__all__ = [
    "Channel",
    "ConsoleChannel",
    "EmailChannel",
    "FeishuChannel",
    "ConsoleMessage",
    "EmailMessage",
    "FeishuMessage",
    "format_text",
]
```

**Step 12: Run all notification tests**

Run: `uv run pytest tests/notification/ -v`
Expected: ALL PASS

**Step 13: Commit**

```bash
git add src/progress/notification/ tests/notification/
git commit -m "feat(notification): add email channel and message
- Add EmailChannel for SMTP delivery
- Add EmailMessage for Jinja2 template rendering
- Add TLS support and SMTP authentication
- Add tests for email channel success and error cases
"
```

---

## Task 6: Configuration Models

**Files:**
- Create: `src/progress/notification/config.py`
- Modify: `src/progress/config.py` (update notification config imports)
- Create: `tests/notification/test_config_models.py`

**Step 1: Write failing test for config models**

Create `tests/notification/test_config_models.py`:

```python
import pytest
from pydantic import ValidationError

from progress.notification.config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
    NotificationChannel,
)


def test_console_channel_config_defaults():
    config = ConsoleChannelConfig()

    assert config.type == "console"
    assert config.enabled is True


def test_feishu_channel_config_validation():
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=10,
    )

    assert config.type == "feishu"
    assert config.enabled is True
    assert config.timeout == 10


def test_feishu_channel_config_requires_url():
    with pytest.raises(ValidationError):
        FeishuChannelConfig(timeout=10)


def test_email_channel_config_validation():
    config = EmailChannelConfig(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )

    assert config.type == "email"
    assert config.port == 587
    assert config.starttls is True


def test_notification_channel_discriminator():
    console = ConsoleChannelConfig()
    feishu = FeishuChannelConfig(webhook_url="https://example.com")
    email = EmailChannelConfig(
        host="smtp.example.com",
        user="user",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )

    channels: list[NotificationChannel] = [console, feishu, email]

    assert isinstance(channels[0], ConsoleChannelConfig)
    assert isinstance(channels[1], FeishuChannelConfig)
    assert isinstance(channels[2], EmailChannelConfig)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notification/test_config_models.py -v`
Expected: FAIL with "No module named 'progress.notification.config'"

**Step 3: Implement configuration models**

Create `src/progress/notification/config.py`:

```python
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, HttpUrl


class ConsoleChannelConfig(BaseModel):
    type: Literal["console"] = "console"
    enabled: bool = True


class FeishuChannelConfig(BaseModel):
    type: Literal["feishu"] = "feishu"
    enabled: bool = True
    webhook_url: HttpUrl
    timeout: int = Field(default=30, ge=1)


class EmailChannelConfig(BaseModel):
    type: Literal["email"] = "email"
    enabled: bool = True
    host: str
    port: int = Field(default=587, ge=1, le=65535)
    user: str
    password: str
    from_addr: EmailStr
    recipient: list[EmailStr]
    starttls: bool = True
    ssl: bool = False


NotificationChannel = Annotated[
    ConsoleChannelConfig | FeishuChannelConfig | EmailChannelConfig,
    Field(discriminator="type"),
]


class NotificationConfig(BaseModel):
    channels: list[NotificationChannel] = Field(default_factory=list)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/notification/test_config_models.py -v`
Expected: ALL PASS

**Step 5: Update main config imports**

Modify `src/progress/config.py` to update the notification config section. Find the existing `NotificationChannelConfig` and `NotificationConfig` and update them:

```python
from progress.notification.config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
    NotificationChannel,
    NotificationConfig,
)
```

Remove old `FeishuChannelConfig`, `EmailChannelConfig` definitions if they exist in config.py.

**Step 6: Run tests to ensure no regressions**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (or adjust if config tests need updates)

**Step 7: Commit**

```bash
git add src/progress/notification/config.py src/progress/config.py tests/notification/test_config_models.py
git commit -m "feat(notification): add Pydantic configuration models
- Add ConsoleChannelConfig with type discriminator
- Add FeishuChannelConfig with URL and timeout
- Add EmailChannelConfig with SMTP settings
- Add NotificationChannel discriminated union
- Add validation tests for all config models
- Update main config.py imports
"
```

---

## Task 7: Factory Functions

**Files:**
- Create: `src/progress/notification/factory.py`
- Create: `tests/notification/test_factory.py`

**Step 1: Write failing test for create_channel**

Create `tests/notification/test_factory.py`:

```python
from progress.notification.config import (
    ConsoleChannelConfig,
    FeishuChannelConfig,
    EmailChannelConfig,
)
from progress.notification.factory import create_channel
from progress.notification.channels import ConsoleChannel, FeishuChannel, EmailChannel


def test_create_channel_returns_console_channel():
    config = ConsoleChannelConfig(enabled=True)
    channel = create_channel(config)

    assert isinstance(channel, ConsoleChannel)


def test_create_channel_returns_feishu_channel():
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=30,
    )
    channel = create_channel(config)

    assert isinstance(channel, FeishuChannel)
    assert channel._webhook_url == "https://example.com/webhook"
    assert channel._timeout == 30


def test_create_channel_returns_email_channel():
    config = EmailChannelConfig(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )
    channel = create_channel(config)

    assert isinstance(channel, EmailChannel)
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/notification/test_factory.py -v`
Expected: FAIL with "No module named 'progress.notification.factory'"

**Step 3: Implement create_channel factory**

Create `src/progress/notification/factory.py`:

```python
from progress.notification.channels import ConsoleChannel, EmailChannel, FeishuChannel
from progress.notification.config import (
    ConsoleChannelConfig,
    EmailChannelConfig,
    FeishuChannelConfig,
    NotificationChannelConfig,
)
from progress.errors import ProgressException


def create_channel(config: NotificationChannelConfig) -> ConsoleChannel | FeishuChannel | EmailChannel:
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
                smtp_host=config.host,
                smtp_port=config.port,
                username=config.user,
                password=config.password,
                from_address=config.from_addr,
                to_addresses=list(config.recipient),
                use_tls=config.starttls,
            )
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/notification/test_factory.py::test_create_channel_returns_console_channel -v`
Run: `uv run pytest tests/notification/test_factory.py::test_create_channel_returns_feishu_channel -v`
Run: `uv run pytest tests/notification/test_factory.py::test_create_channel_returns_email_channel -v`
Expected: ALL PASS

**Step 5: Write failing test for create_message**

Add to `tests/notification/test_factory.py`:

```python
from progress.notification.messages import ConsoleMessage, FeishuMessage, EmailMessage
from progress.notification.factory import create_message


def test_create_message_returns_console_message():
    config = ConsoleChannelConfig(enabled=True)
    channel = create_channel(config)
    message = create_message(config, channel, text="Test text")

    assert isinstance(message, ConsoleMessage)


def test_create_message_returns_feishu_message():
    config = FeishuChannelConfig(
        webhook_url="https://example.com/webhook",
        timeout=30,
    )
    channel = create_channel(config)
    message = create_message(
        config,
        channel,
        title="Test Title",
        summary="Test summary",
        total_commits=10,
    )

    assert isinstance(message, FeishuMessage)


def test_create_message_returns_email_message():
    config = EmailChannelConfig(
        host="smtp.example.com",
        port=587,
        user="user@example.com",
        password="pass",
        from_addr="from@example.com",
        recipient=["to@example.com"],
    )
    channel = create_channel(config)
    message = create_message(
        config,
        channel,
        subject="Test Subject",
        body="Test body",
        template_data={},
    )

    assert isinstance(message, EmailMessage)
```

**Step 6: Run test to verify it fails**

Run: `uv run pytest tests/notification/test_factory.py::test_create_message_returns_console_message -v`
Expected: FAIL with "create_message not defined"

**Step 7: Implement create_message factory**

Add to `src/progress/notification/factory.py`:

```python
from progress.notification.messages import ConsoleMessage, EmailMessage, FeishuMessage
from typing import Any


def create_message(
    config: NotificationChannelConfig,
    channel: ConsoleChannel | FeishuChannel | EmailChannel,
    **kwargs: Any,
) -> ConsoleMessage | FeishuMessage | EmailMessage:
    match config.type:
        case "console":
            return ConsoleMessage(channel, text=kwargs.get("text", ""))
        case "feishu":
            return FeishuMessage(
                channel,
                title=kwargs.get("title", ""),
                summary=kwargs.get("summary", ""),
                total_commits=kwargs.get("total_commits", 0),
                repo_statuses=kwargs.get("repo_statuses"),
                markpost_url=kwargs.get("markpost_url"),
                batch_index=kwargs.get("batch_index"),
                total_batches=kwargs.get("total_batches"),
            )
        case "email":
            return EmailMessage(
                channel,
                subject=kwargs.get("subject", ""),
                body=kwargs.get("body", ""),
                template_data=kwargs.get("template_data", {}),
            )
        case _:
            raise ProgressException(f"Unknown notification channel type: {config.type}")
```

**Step 8: Run all factory tests**

Run: `uv run pytest tests/notification/test_factory.py -v`
Expected: ALL PASS

**Step 9: Update package exports**

Update `src/progress/notification/__init__.py`:

```python
from .base import Channel
from .channels import ConsoleChannel, EmailChannel, FeishuChannel
from .factory import create_channel, create_message
from .messages import ConsoleMessage, EmailMessage, FeishuMessage
from .utils import format_text

__all__ = [
    "Channel",
    "ConsoleChannel",
    "EmailChannel",
    "FeishuChannel",
    "ConsoleMessage",
    "EmailMessage",
    "FeishuMessage",
    "create_channel",
    "create_message",
    "format_text",
]
```

**Step 10: Commit**

```bash
git add src/progress/notification/factory.py src/progress/notification/__init__.py tests/notification/test_factory.py
git commit -m "feat(notification): add factory functions for channels and messages
- Add create_channel() factory function
- Add create_message() factory function
- Support ConsoleChannel, FeishuChannel, EmailChannel creation from config
- Add tests for factory functions
"
```

---

## Task 8: Migrate CLI Call Sites

**Files:**
- Modify: `src/progress/cli.py` (5 call sites)

**Step 1: Read existing notification call sites**

Run: `grep -n "notification_manager.send" src/progress/cli.py`
Expected: Shows 5 locations around lines 277, 396, 457, 510

**Step 2: Update first call site - _send_notification()**

Find the `_send_notification` function around line 277 and replace:

```python
def _send_notification(
    notification_config: NotificationConfig,
    summary: str,
    batch_commit_count: int,
    report_url: str | None,
    repo_statuses: dict[str, str],
    batches: list,
    batch,
) -> None:
    from progress.notification import create_channel, create_message

    if not notification_config.channels:
        return

    failures: list[Exception] = []

    for channel_config in notification_config.channels:
        if not channel_config.enabled:
            continue

        try:
            channel = create_channel(channel_config)
            message = create_message(
                channel_config,
                channel,
                title=_("Progress Report for Open Source Projects"),
                summary=summary,
                total_commits=batch_commit_count,
                markpost_url=report_url,
                repo_statuses=repo_statuses,
                batch_index=batch.batch_index,
                total_batches=len(batches),
            )
            message.send(fail_silently=True)
        except Exception as e:
            failures.append(e)
            logger.error("Notification channel failed: %s", e)

    if failures:
        logger.warning("Some notifications failed: %s", failures)
```

**Step 3: Update second call site - _send_discovered_repos_notification()**

Find the function around line 396 and replace:

```python
def _send_discovered_repos_notification(
    notification_config: NotificationConfig,
    title: str,
    summary: str | None,
    new_repos: list,
) -> None:
    from progress.notification import create_channel, create_message

    if not notification_config.channels:
        return

    failures: list[Exception] = []

    for channel_config in notification_config.channels:
        if not channel_config.enabled:
            continue

        try:
            channel = create_channel(channel_config)
            message = create_message(
                channel_config,
                channel,
                title=title,
                summary=summary or f"Discovered {len(new_repos)} new repositories",
                total_commits=0,
                repo_statuses={},
            )
            message.send(fail_silently=True)
        except Exception as e:
            failures.append(e)
            logger.error("Notification channel failed: %s", e)

    if failures:
        logger.warning("Some notifications failed: %s", failures)
```

**Step 4: Update third call site - _send_proposal_events_notification()**

Find the function around line 457 and replace:

```python
def _send_proposal_events_notification(
    notification_config: NotificationConfig,
    title: str,
    summary: str | None,
    events: list,
) -> None:
    from progress.notification import create_channel, create_message

    if not notification_config.channels:
        return

    repo_statuses = {
        f"{e.tracker_type}#{e.proposal_number}": "success" for e in events
    }

    failures: list[Exception] = []

    for channel_config in notification_config.channels:
        if not channel_config.enabled:
            continue

        try:
            channel = create_channel(channel_config)
            message = create_message(
                channel_config,
                channel,
                title=title,
                summary=summary or f"Processed {len(events)} proposal events",
                total_commits=0,
                repo_statuses=repo_statuses,
            )
            message.send(fail_silently=True)
        except Exception as e:
            failures.append(e)
            logger.error("Notification channel failed: %s", e)

    if failures:
        logger.warning("Some notifications failed: %s", failures)
```

**Step 5: Update fourth call site - _send_changelog_update_notification()**

Find the function around line 510 and replace:

```python
def _send_changelog_update_notification(
    notification_config: NotificationConfig,
    markpost_client: MarkpostClient,
    updates,
    all_results,
    timezone: str,
) -> None:
    from progress.notification import create_channel, create_message

    if not notification_config.channels:
        return

    title = _("New Version Detected")
    summaries = []
    repo_statuses = {}

    for update in updates:
        summaries.append(f"{update.name} {update.version}: {update.description}")

    for r in all_results:
        if r.status == "success":
            repo_statuses[r.name] = "success"
        else:
            repo_statuses[r.name] = "failed"

    summary = "\n".join(summaries)

    failures: list[Exception] = []

    for channel_config in notification_config.channels:
        if not channel_config.enabled:
            continue

        try:
            channel = create_channel(channel_config)
            message = create_message(
                channel_config,
                channel,
                title=title,
                summary=summary,
                total_commits=0,
                repo_statuses=repo_statuses,
            )
            message.send(fail_silently=True)
        except Exception as e:
            failures.append(e)
            logger.error("Notification channel failed: %s", e)

    if failures:
        logger.warning("Some notifications failed: %s", failures)
```

**Step 6: Update imports in cli.py**

Add at the top of `src/progress/cli.py`:

```python
from progress.notification import create_channel, create_message
```

Remove old import if present:
```python
from progress.notification import NotificationManager, NotificationMessage
```

**Step 7: Run manual smoke test**

Run: `uv run progress check --help` to verify imports work

**Step 8: Commit**

```bash
git add src/progress/cli.py
git commit -m "refactor(notification): migrate call sites to new framework
- Update _send_notification() to use new API
- Update _send_discovered_repos_notification() to use new API
- Update _send_proposal_events_notification() to use new API
- Update _send_changelog_update_notification() to use new API
- All call sites now use create_channel() and create_message()
"
```

---

## Task 9: Remove Old Notification Code

**Files:**
- Delete: `src/progress/notification.py` (old monolithic file)
- Modify: `src/progress/cli.py` (remove old imports)

**Step 1: Verify old file is no longer imported**

Run: `grep -r "from progress.notification import NotificationManager\|NotificationMessage" src/progress/`
Expected: No matches (already updated in Task 8)

**Step 2: Delete old notification file**

Run: `rm src/progress/notification.py`

**Step 3: Verify imports still work**

Run: `uv run python -c "from progress.notification import create_channel, create_message; print('Imports OK')"`
Expected: "Imports OK"

**Step 4: Run all notification tests**

Run: `uv run pytest tests/notification/ -v`
Expected: ALL PASS

**Step 5: Run all tests to check for regressions**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS (or fix any remaining issues)

**Step 6: Commit**

```bash
git add src/progress/notification.py
git commit -m "refactor(notification): remove old notification.py file
- Delete monolithic notification.py
- All functionality now in src/progress/notification/ package
- Preserved all existing features with new architecture
"
```

---

## Task 10: Update Documentation

**Files:**
- Modify: `CLAUDE.md` (update notification section)
- Modify: `README.md` or `README_zh.md` (if applicable)

**Step 1: Update CLAUDE.md**

Find the notification section and update to reflect new architecture:

```markdown
## Notification System

The notification system uses a protocol-based architecture with separation of concerns:
- **Channels** handle transport only (Console, Feishu, Email)
- **Messages** handle formatting and business logic
- **Factory functions** create instances from Pydantic config

**Usage:**
```python
from progress.notification import create_channel, create_message

channel = create_channel(channel_config)
message = create_message(
    channel_config,
    channel,
    title="Notification Title",
    summary="Summary text",
    total_commits=10,
    repo_statuses={"repo1": "success"},
)
message.send(fail_silently=True)
```

**Adding a new notification channel:**
1. Implement Channel protocol with `send(payload: str) -> None`
2. Create corresponding Message class with `get_payload() -> str`
3. Add Pydantic config model with discriminator
4. Update factory functions to handle new type
```

**Step 2: Update README if needed**

Check if README mentions notifications, update if present.

**Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs(notification): update documentation for new architecture
- Update CLAUDE.md with new notification system design
- Document factory functions usage
- Add guide for adding new notification channels
"
```

---

## Task 11: Final Verification

**Files:**
- No file changes, verification only

**Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run type checking**

Run: `uv run ruff check src/progress/notification/`
Expected: No errors

**Step 3: Run formatting check**

Run: `uv run ruff format --check src/progress/notification/`
Expected: No changes needed

**Step 4: Manual smoke test**

Run: `uv run progress check --help`
Expected: Command works without import errors

**Step 5: Verify config compatibility**

Check that existing `config.toml` files still work:

Run: `uv run progress check -c config/simple.toml`
Expected: Runs without config errors

**Step 6: Final commit**

```bash
git add .
git commit -m "refactor(notification): complete framework migration
- All tests passing
- Type checking clean
- Documentation updated
- Ready for production use
"
```

---

## Summary

This implementation plan creates a complete notification framework refactoring with:

- **3 channels**: Console, Feishu, Email
- **3 messages**: Console text, Feishu JSON card, Email HTML
- **Type-safe config**: Pydantic discriminated unions
- **Error handling**: fail_silently flag, custom exceptions
- **Full test coverage**: Unit tests for all components
- **Factory pattern**: Easy instantiation from config
- **Breaking change**: Updated all 5 call sites in cli.py

Total estimated tasks: 11 major tasks, 70+ individual steps following TDD.

### Key Migration Points

1. **Preserved functionality**: Feishu card structure, Jinja2 templates, batch tracking all maintained
2. **Clean separation**: Messages format, Channels transport
3. **Better extensibility**: Add new channel = implement protocol + message class + factory case
4. **Console channel added**: New feature for local development and debugging
