# Logging Guidelines

> How logging is done in this project.

---

## Overview

This project uses Python's standard `logging` module with a rotating file handler. Configuration is in `src/progress/log.py`.

Log files:
- **Console**: INFO level and above
- **File**: DEBUG level and above (`data/progress.log`)
- **Rotation**: 5MB max, 100 backups

---

## Log Levels

| Level | When to Use | Example |
|-------|-------------|---------|
| `DEBUG` | Detailed diagnostic info | `logger.debug(f"Processing repo: {repo_name}")` |
| `INFO` | Normal operation milestones | `logger.info("Database tables created")` |
| `WARNING` | Unexpected but recoverable | `logger.warning(f"Upload failed, using fallback: {e}")` |
| `ERROR` | Operation failed, needs attention | `logger.error(f"Application error: {e}", exc_info=True)` |

---

## Getting a Logger

```python
import logging

logger = logging.getLogger(__name__)
```

Always use `__name__` to get a logger - this creates a hierarchical logger under `progress`.

---

## Log Format

```
%(asctime)s [%(levelname)s] [%(processName)s] [%(threadName)s] - %(message)s
```

Example output:
```
2024-01-15 10:30:45,123 [INFO] [MainProcess] [MainThread] - Loading configuration file: config.toml
```

---

## What to Log

### Log These Events

- Application startup/shutdown
- Configuration loading
- Database operations (create, sync, migrate)
- External API calls (GitHub, AI analysis)
- Notification sends (success/failure)
- Batch processing progress
- Error conditions with context

### Example: Operation Progress

```python
logger.info(f"Starting to check {len(repos)} repositories")
# ... work ...
logger.info(f"Checked {len(reports)} repositories, {total_commits} commits total")
```

### Example: External Operations

```python
logger.info(f"Loading configuration file: {config}")
logger.info("Generating title and summary with Claude...")
logger.info(f"Batch {batch_index + 1} uploaded: {markpost_url}")
```

### Example: Errors with Context

```python
logger.error(f"Failed to save report for {repo_name}: {db_error}")
logger.warning(f"Some notifications failed: {failures}/{len(enabled_channels)}")
```

---

## What NOT to Log

### Never Log These

- **Secrets**: API tokens, passwords, webhook URLs
- **PII**: User email addresses, personal data
- **Full configuration**: Contains sensitive values
- **Raw API responses**: May contain sensitive data

### Safe Logging Patterns

```python
# Bad - logs sensitive token
logger.info(f"Using token: {token}")

# Good - masks sensitive data
logger.info("Using configured GitHub token")

# Bad - logs full config with secrets
logger.info(f"Config: {config}")

# Good - logs only non-sensitive parts
logger.info(f"Loaded config with {len(repos)} repositories")
```

---

## Structured Logging Patterns

### Using f-strings

```python
# Preferred - readable and efficient
logger.info(f"Processing batch {batch_index + 1}/{total_batches}")
```

### Using % formatting for lazy evaluation

```python
# Use % formatting when the log may not be output
logger.debug("Processing item %s with value %s", item_id, value)
```

### Including exception info

```python
try:
    risky_operation()
except Exception as e:
    # exc_info=True includes full stack trace
    logger.error(f"Operation failed: {e}", exc_info=True)
```

---

## Common Mistakes

### 1. Using print() instead of logging

```python
# Bad
print(f"Processing {name}")

# Good
logger.info(f"Processing {name}")
```

### 2. Logging at wrong level

```python
# Bad - normal operation at ERROR level
logger.error(f"Processing repository {name}")

# Good - normal operation at INFO level
logger.info(f"Processing repository {name}")
```

### 3. Not including context

```python
# Bad - no context for debugging
logger.error("Failed to save")

# Good - includes what and why
logger.error(f"Failed to save report for {repo_name}: {e}")
```

### 4. Logging sensitive data

```python
# Bad - exposes webhook URL
logger.info(f"Sending to webhook: {webhook_url}")

# Good - logs action without sensitive data
logger.info("Sending notification to Feishu channel")
```
