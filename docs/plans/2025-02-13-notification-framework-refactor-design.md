# Notification Framework Refactor Design

**Date:** 2025-02-13
**Status:** Approved
**Type:** Refactoring

## Overview

Refactor the notification system to adopt the feeber framework architecture - a strict protocol-based design that separates message formatting from transport delivery. The current system couples formatting logic in channel implementations; the new architecture moves formatting to Message classes while Channels handle only transport.

## Goals

- **Clean separation** - Messages handle formatting and business logic, Channels handle transport only
- **Better extensibility** - Add new notification types by implementing Channel + Message pair
- **Add Console channel** - Enable stdout/stderr notifications for debugging and local development
- **Preserve functionality** - All existing features work exactly the same (Feishu cards, email templates, batch tracking, changelog notifications)

## Architecture

### Protocol-Based Design

**Three-layer protocol:**
```
Pydantic Config → Channel Instance → Message Instance → send() → Transport
```

**Layers:**
1. **Channel Protocol** (`base.py`): Contract is `send(self, payload: str) -> None`
2. **Message Classes** (`messages/`): Own formatting logic, couple to specific channel types
3. **Channel Implementations** (`channels/`): Pure transport - Console, Feishu, Email

### Key Changes from Current

**Before:**
```python
class NotificationChannel(Protocol):
    def send(self, message: NotificationMessage) -> None: ...

class FeishuNotification:
    def send(self, message: NotificationMessage) -> None:
        card = self._build_card(message)  # formatting here
        self._post_card(card)
```

**After:**
```python
class Channel(Protocol):
    def send(self, payload: str) -> None: ...

class FeishuChannel:
    def send(self, payload: str) -> None:
        # transport only
        requests.post(self.webhook_url, json=payload, timeout=self.timeout)

class FeishuMessage(Message):
    def get_payload(self) -> str:
        # formatting here
        return json.dumps(self._build_card())
```

### What Stays Exactly the Same

- Feishu card structure (header, elements, stats, repo lists, action buttons)
- Jinja2 email templates and rendering
- Batch tracking (`batch_index`, `total_batches`)
- Changelog notification support
- Configuration TOML structure (user-facing)
- Error handling strategy (fail_silently flag, aggregate failures)
- Internationalization (`_()`)

### What Changes

- `NotificationChannel` protocol: `send(message)` → `send(payload: str)`
- `NotificationMessage` dataclass removed; replaced by domain-specific Message classes
- Feishu/Email channels: formatting logic moves to Message classes
- `NotificationManager`: simplified factory pattern
- Call sites in `cli.py`: use new message-based API
- Add Console channel for stdout notifications

## Component Structure

```
src/progress/notification/
├── __init__.py              # Public exports
├── base.py                  # Channel Protocol
├── channels/
│   ├── __init__.py
│   ├── console.py           # ConsoleChannel (NEW)
│   ├── feishu.py            # FeishuChannel (transport only)
│   └── email.py             # EmailChannel (transport only)
├── messages/
│   ├── __init__.py
│   ├── base.py              # Message ABC
│   ├── console.py           # ConsoleMessage
│   ├── feishu.py            # FeishuMessage (card formatting)
│   └── email.py             # EmailMessage (Jinja2 rendering)
└── utils.py                 # Text formatting utilities

tests/notification/
├── test_channel_protocol.py      # Protocol compliance
├── test_base_message.py           # Message.send() behavior
├── channels/
│   ├── test_console_channel.py
│   ├── test_feishu_channel.py    # Mock HTTP
│   └── test_email_channel.py     # Mock SMTP
├── messages/
│   ├── test_console_message.py
│   ├── test_feishu_message.py    # Card formatting
│   └── test_email_message.py     # Jinja2 rendering
└── test_utils.py
```

### Component Responsibilities

- **`base.py`**: `Channel` protocol with `send(payload: str) -> None` method
- **`channels/console.py`**: `ConsoleChannel` prints to stdout with logging
- **`channels/feishu.py`**: `FeishuChannel` HTTP POST for Feishu webhooks (transport only)
- **`channels/email.py`**: `EmailChannel` SMTP delivery (transport only)
- **`messages/base.py`**: `Message` ABC with `get_channel()`, `get_payload()`, `send(fail_silently)`
- **`messages/console.py`**: `ConsoleMessage` formats plain text
- **`messages/feishu.py`**: `FeishuMessage` builds Feishu JSON card (preserves existing card structure)
- **`messages/email.py`**: `EmailMessage` renders Jinja2 templates, returns HTML
- **`utils.py`**: Text formatting helpers (format stats, repo lists, etc.)

## Data Flow

### Current Flow

```
cli.py → NotificationManager.send(NotificationMessage)
       → Channel.send(NotificationMessage)
       → Channel formats + sends
```

### New Flow

```
cli.py → For each channel_config:
        → create_channel(channel_config) → Channel
        → create_message(channel_config, channel, **data) → Message
        → message.send(fail_silently=True)
           → message.get_payload() formats data
           → channel.send(payload) delivers
```

### Call Site Migration Example

**Before:**
```python
notification_manager.send(
    NotificationMessage(
        title=_("Progress Report for Open Source Projects"),
        summary=summary,
        total_commits=batch_commit_count,
        markpost_url=report_url,
        repo_statuses=repo_statuses,
        batch_index=batch.batch_index,
        total_batches=len(batches),
    )
)
```

**After:**
```python
for channel_config in config.notification.channels:
    if not channel_config.enabled:
        continue

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
```

### Helper Functions

- **`create_channel(config)`**: Factory returns ConsoleChannel, FeishuChannel, or EmailChannel
- **`create_message(config, channel, **data)`**: Factory returns appropriate Message type

## Error Handling

**Three-tier strategy (preserved from current design):**

### 1. Message Level

`fail_silently` flag in `Message.send()`:
```python
def send(self, fail_silently: bool = True) -> bool:
    try:
        self.get_channel().send(self.get_payload())
        logger.info("Notification sent successfully")
        return True
    except Exception as e:
        logger.warning("Channel failed: %s", e)
        if not fail_silently:
            raise
        return False
```

### 2. Channel Level

Custom exceptions for transport failures:
```python
class FeishuChannel:
    def send(self, payload: str) -> None:
        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=self.timeout)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise ExternalServiceException(f"Feishu notification failed: {e}") from e
```

### 3. Application Level

Iterate channels, don't let one failure block others:
```python
failures: list[Exception] = []
for channel_config in config.notification.channels:
    if channel_config.enabled:
        try:
            channel = create_channel(channel_config)
            message = create_message(channel_config, channel, **data)
            message.send(fail_silently=True)
        except Exception as e:
            failures.append(e)
            logger.error("Notification channel failed: %s", e)
```

**Logging Levels:**
- `DEBUG`: Message preparation, channel instantiation
- `INFO`: Successful send operations
- `WARNING`: Failed sends with `fail_silently=True`
- `ERROR`: Failed sends with `fail_silently=False`, unexpected errors

## Configuration

### Pydantic Models

```python
class ConsoleChannelConfig(BaseModel):
    type: Literal["console"] = "console"
    enabled: bool = True

class FeishuChannelConfig(BaseModel):
    type: Literal["feishu"] = "feishu"
    enabled: bool = True
    webhook_url: HttpUrl
    timeout: int = 30

class EmailChannelConfig(BaseModel):
    type: Literal["email"] = "email"
    enabled: bool = True
    host: str
    port: int = 587
    user: str
    password: str
    from_addr: str
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

### config.toml

```toml
[notification.channels]
type = "console"
enabled = true

[[notification.channels]]
type = "feishu"
enabled = true
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/..."
timeout = 30

[[notification.channels]]
type = "email"
enabled = true
host = "smtp.gmail.com"
port = 587
user = "user@example.com"
password = "${EMAIL_PASSWORD}"
from_addr = "alerts@example.com"
recipient = ["ops@example.com"]
starttls = true
```

**Note:** User config files remain backward compatible - only adding new console option.

## Testing Strategy

### Core Coverage Approach

```
tests/notification/
├── test_channel_protocol.py      # Protocol compliance
├── test_base_message.py           # Message.send() behavior
├── channels/
│   ├── test_console_channel.py   # stdout capture
│   ├── test_feishu_channel.py    # Mock HTTP
│   └── test_email_channel.py     # Mock SMTP
├── messages/
│   ├── test_console_message.py   # Text formatting
│   ├── test_feishu_message.py    # Card structure
│   └── test_email_message.py     # Jinja2 rendering
└── test_utils.py
```

### Test Coverage

1. **Protocol tests** - Verify channel implementations conform to `Channel` protocol
2. **Base Message tests** - Test `send()`, `fail_silently` flag, error handling
3. **Channel tests** - Mock transport layer (SMTP, HTTP), verify payload delivery
4. **Message tests** - Verify payload formatting for each channel type
5. **Migration tests** - Ensure new API produces equivalent output to old

### Testing Tools

- `pytest` for test framework
- `unittest.mock.Mock` for mocking external services
- `requests_mock` for Feishu webhook integration tests
- Jinja2 template testing for EmailMessage

## Migration Approach

### Big Bang Replacement - Breaking Change with Coordinated Updates

**Step 1: Create new framework alongside old**
- Create `src/progress/notification/` package with new architecture
- Keep existing `src/progress/notification.py` working unchanged
- No breaking changes yet

**Step 2: Implement channels and messages (TDD)**
1. Base protocol + Message ABC
2. ConsoleChannel + ConsoleMessage (simplest, new feature)
3. FeishuChannel + FeishuMessage (most complex, preserves card formatting)
4. EmailChannel + EmailMessage
5. Update config models (rename FeishuChannelConfig type)
6. Factory functions

**Step 3: Migrate call sites**
Update 5 locations in `cli.py`:
1. `_send_notification()` - Line ~277 (batch report notifications)
2. `_send_discovered_repos_notification()` - Line ~396 (new repos discovery)
3. `_send_proposal_events_notification()` - Line ~457 (proposal events)
4. `_send_changelog_update_notification()` - Line ~510 (changelog updates)

**Step 4: Remove old code**
- Delete `src/progress/notification.py`
- Remove `NotificationMessage`, `FeishuNotification`, `EmailNotification`, `NotificationManager`
- Update all imports

**Step 5: Update tests**
- Port existing notification tests to new framework
- Add tests for Console channel/message
- Update config model tests

### Estimated Implementation Order

1. Console channel/message (new feature, simple)
2. Base Message + protocol tests
3. Feishu channel/message (preserve card formatting)
4. Email channel/message (preserve Jinja2 templates)
5. Update config models
6. Factory functions
7. Migrate call sites
8. Remove old code
9. Update all tests

## Integration Points

**Files to delete:**
- `src/progress/notification.py` (old monolithic file)

**Files to create:**
- `src/progress/notification/__init__.py`
- `src/progress/notification/base.py`
- `src/progress/notification/channels/` (3 channels)
- `src/progress/notification/messages/` (3 messages)
- `src/progress/notification/utils.py`
- `tests/notification/` (full test suite)

**Files to modify:**
- `src/progress/config.py` - Update imports, add ConsoleChannelConfig
- `src/progress/cli.py` - Update 5 call sites
- `src/progress/errors.py` - Ensure ExternalServiceException exists

**Files that remain unchanged:**
- `src/progress/templates/` - All Jinja2 templates
- `src/progress/consts.py` - Template constants
- `src/progress/i18n.py` - Internationalization
- `src/progress/models.py` - All Peewee models

## Success Criteria

### Functional Requirements

- All existing features work exactly the same (no behavior changes)
- Feishu card structure preserved (header, stats, repo lists, action buttons)
- Email rendering preserved (Jinja2 templates, HTML output)
- Batch tracking preserved (`batch_index`, `total_batches`)
- Changelog notifications preserved
- Console channel works (stdout output)
- All call sites in `cli.py` updated and working

### Architectural Requirements

- Protocol-based design: `Channel` protocol with `send(payload: str) -> None`
- Separation of concerns: Messages format, Channels transport
- Factory pattern for channel/message instantiation
- Pydantic discriminated unions for type-safe config
- No Impl suffix in class names (ConsoleChannel, not ConsoleChannelImpl)

### Quality Requirements

- All new code follows project standards (imports at top, self-documenting, type hints)
- Unit tests for all components (base, channels, messages)
- No new external dependencies (use existing: requests, jinja2, pydantic)
- Type checking passes (tyro or mypy if configured)
- Linting passes (ruff)

### Testing Requirements

- All tests pass before merge
- Protocol compliance tests verify Channel implementations
- Message tests verify payload formatting
- Channel tests verify transport with mocked dependencies
- Manual verification: `uv run progress check` sends notifications

### Migration Requirements

- Old `notification.py` file deleted
- All 5 call sites in `cli.py` updated
- Config imports updated
- No breaking changes to user `config.toml` files
- Single PR with atomic commits

### Maintainability Requirements

- Clean separation: notification code isolated in `src/progress/notification/`
- Easy to extend: new notification type = implement Channel + Message pair
- Easy to test: all components mockable
- Clear documentation: docstrings for public API
