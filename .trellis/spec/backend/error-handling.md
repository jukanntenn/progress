# Error Handling

> How errors are handled in this project.

---

## Overview

This project uses a hierarchical exception system defined in `src/progress/errors.py`. All custom exceptions inherit from `ProgressException`, allowing for both specific and catch-all handling.

Key principles:
- Use specific exception types for specific error categories
- All exceptions should have clear, actionable messages
- Catch and wrap external library exceptions with context

---

## Error Types

### Exception Hierarchy

```
ProgressException (base)
├── ConfigException          # Configuration loading/validation errors
├── GitException             # Git/GitHub operation failures
├── AnalysisException        # AI analysis failures
├── CommandException         # External command execution failures
├── ClientError              # HTTP 4xx errors (no retry)
├── ExternalServiceException # External service call failures
├── ProposalParseError       # Proposal parsing failures
└── ChangelogParseError      # Changelog parsing failures
```

### Exception Definitions

Each exception class documents when to use it:

```python
class ConfigException(ProgressException):
    """Raised when configuration validation or loading fails.

    Use this exception when:
    - The configuration file cannot be found
    - The TOML syntax is invalid
    - Configuration validation fails (missing required fields, invalid values)
    - Type conversion of config values fails
    """
    pass


class GitException(ProgressException):
    """Raised when GitHub/Git operations fail.

    Use this exception when:
    - Git command execution fails (clone, fetch, checkout, etc.)
    - GitHub API calls fail
    - Repository operations encounter errors
    - Git authentication fails
    """
    pass
```

---

## Error Handling Patterns

### Raising Exceptions with Clear Messages

```python
# Good - includes context and what went wrong
raise ConfigException(f"Configuration file not found: {config_path}")

# Good - includes what was expected vs what was received
raise ConfigException(
    f"Invalid timezone configuration: '{tz}'. "
    "Please use a valid IANA timezone identifier"
)

# Bad - vague message
raise ConfigException("Error loading config")
```

### Wrapping External Exceptions

```python
try:
    config = Config.load_from_file(config_path)
except ValidationError as e:
    # Wrap with context
    error_lines = ["Configuration validation failed:"]
    for error in e.errors():
        loc = " -> ".join(str(item) for item in error["loc"])
        error_lines.append(f"  - {loc}: {error['msg']}")
    raise ConfigException("\n".join(error_lines)) from e
```

### In CLI Commands

```python
try:
    cfg = Config.load_from_file(config)
    # ... work ...
except ProgressException as e:
    logger.error(f"Application error: {e}", exc_info=True)
    raise click.ClickException(str(e))
except Exception as e:
    logger.error(f"Program execution failed: {e}", exc_info=True)
    raise click.ClickException(str(e))
finally:
    close_db()
```

### Graceful Degradation

```python
# Continue with defaults if non-critical operation fails
try:
    markpost_url = markpost_client.upload(content, title)
except Exception as e:
    logger.warning(f"Upload failed, continuing without URL: {e}")
    markpost_url = ""
```

### Collecting Multiple Errors

```python
errors = []
for channel in channels:
    try:
        channel.send(message)
    except Exception as e:
        errors.append((channel.name, str(e)))

if errors:
    logger.warning(f"Some channels failed: {errors}")
```

---

## API Error Responses

### FastAPI HTTPException

```python
from fastapi import HTTPException

@router.get("/{report_id}")
def get_report(report_id: int):
    report = Report.get_or_none(Report.id == report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report
```

### Distinguishing Client vs Server Errors

```python
# ClientError for 4xx - should not be retried
if 400 <= status_code < 500:
    raise ClientError(f"Client error {status_code}: {response.text}")

# Other errors may be transient
raise ExternalServiceException(f"Request failed: {response.text}")
```

---

## Logging with Exceptions

Always log exceptions with `exc_info=True` for stack traces:

```python
try:
    result = external_api.call()
except ExternalServiceException as e:
    logger.error(f"External API call failed: {e}", exc_info=True)
```

For warnings that shouldn't stop execution:

```python
try:
    title, summary = analyzer.generate_title_and_summary(content)
except Exception as e:
    logger.warning(f"Failed to generate title/summary: {e}")
    title = "Default Title"
    summary = ""
```

---

## Common Mistakes

### 1. Catching too broadly without logging

```python
# Bad - silently swallows all errors
try:
    do_something()
except:
    pass

# Good - log and handle appropriately
try:
    do_something()
except Exception as e:
    logger.warning(f"Operation failed, using fallback: {e}")
```

### 2. Not using specific exception types

```python
# Bad - generic exception
raise Exception("Config invalid")

# Good - specific type with context
raise ConfigException(f"Invalid config: {reason}")
```

### 3. Losing exception context

```python
# Bad - loses original exception
try:
    config = load_config()
except Exception:
    raise ConfigException("Failed to load config")

# Good - preserves chain
try:
    config = load_config()
except Exception as e:
    raise ConfigException("Failed to load config") from e
```

### 4. Not handling cleanup in finally

```python
# Bad - resource leak on error
def process():
    init_db()
    do_work()  # If this raises, DB stays open
    close_db()

# Good - always cleanup
def process():
    try:
        init_db()
        do_work()
    finally:
        close_db()
```
