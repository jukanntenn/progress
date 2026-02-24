# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

This project follows Python best practices with enforcement via:
- **Type hints** on all public functions
- **Pydantic** for data validation
- **pytest** for testing
- **uv** for package management

---

## Forbidden Patterns

### 1. Comments explaining WHAT code does

```python
# Bad - comment explains obvious code
# Loop through repos and check each one
for repo in repos:
    check(repo)

# Good - self-documenting code
for repo in repos:
    check_repository(repo)
```

Only add comments explaining WHY something is done:
```python
# Good - explains non-obvious decision
# Use batch_size=100 to avoid memory issues with large diffs
batches = split_into_batches(items, batch_size=100)
```

### 2. Hardcoded secrets

```python
# Bad - hardcoded token
token = "ghp_xxxxx"

# Good - from configuration
token = config.github.gh_token
```

### 3. Bare except clauses

```python
# Bad - catches everything including KeyboardInterrupt
try:
    do_something()
except:
    pass

# Good - catch specific exceptions
try:
    do_something()
except (ValueError, KeyError) as e:
    logger.warning(f"Expected error: {e}")
```

### 4. Mutable default arguments

```python
# Bad - mutable default
def process(items=[]):
    ...

# Good - None default with explicit check
def process(items=None):
    if items is None:
        items = []
```

### 5. Star imports

```python
# Bad - pollutes namespace
from module import *

# Good - explicit imports
from module import specific_function, AnotherClass
```

---

## Required Patterns

### 1. Type hints on public functions

```python
# Good
def load_from_file(config_path: str) -> "Config":
    ...

def get_timezone(self) -> ZoneInfo:
    ...
```

### 2. Pydantic models for data validation

```python
# Good
class RepositoryConfig(BaseModel):
    url: str
    branch: str = "main"
    enabled: bool = True

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v:
            raise ValueError("Repository URL cannot be empty")
        return v
```

### 3. Docstrings for modules and classes

```python
class Config(BaseSettings):
    """Application configuration.

    Loads from TOML file with environment variable overrides.
    Supports PROGRESS_ prefix and __ nested delimiter.
    """
```

### 4. Context managers for resources

```python
# Good - automatic cleanup
with open(config_path) as f:
    content = f.read()
```

### 5. f-strings for string formatting

```python
# Good
message = f"Processing {repo_name} with {commit_count} commits"

# Bad
message = "Processing {} with {} commits".format(repo_name, commit_count)
```

---

## Testing Requirements

### Test Structure

Tests must mirror the source structure:

```
src/progress/
├── config.py          → tests/test_config.py
├── db/models.py       → tests/db/test_models.py
└── utils/text.py      → tests/utils/test_text.py
```

### Test Naming

```python
# Pattern: test_<function>_<scenario>_<expected>
def test_load_from_file_with_only_required_fields():
    ...

def test_invalid_timezone():
    ...

def test_env_overrides_file_config():
    ...
```

### Use pytest fixtures

```python
@pytest.fixture
def temp_config_file():
    """Create a temporary config file"""
    fd, path = tempfile.mkstemp(suffix=".toml")
    os.close(fd)
    yield path
    os.unlink(path)


def test_load_config(temp_config_file):
    Path(temp_config_file).write_text(content)
    config = Config.load_from_file(temp_config_file)
    assert config is not None
```

### Run tests before commit

```bash
uv run pytest -v
```

---

## Code Review Checklist

### Before Submitting

- [ ] All imports at the top of the file
- [ ] Type hints on public functions
- [ ] No hardcoded secrets or sensitive data
- [ ] Error handling with appropriate exception types
- [ ] Logging for important operations
- [ ] Tests pass: `uv run pytest -v`

### For Reviewers

- [ ] Code is self-documenting (minimal comments needed)
- [ ] Follows existing patterns in the codebase
- [ ] Error messages are clear and actionable
- [ ] No performance regressions
- [ ] Database operations handle cleanup

---

## Common Quality Issues

### 1. Missing type hints

```python
# Bad
def process(data):
    return data.value

# Good
def process(data: Config) -> str:
    return data.value
```

### 2. Long functions

If a function exceeds ~50 lines, consider breaking it into smaller functions:

```python
# Instead of one long function
def process_reports(config, check_result, ...):
    # 100+ lines
    ...

# Break into smaller functions
def process_reports(config, check_result, ...):
    reports = _prepare_reports(check_result)
    _save_to_database(reports)
    _send_notifications(reports)
```

### 3. Deeply nested conditionals

```python
# Bad - hard to read
if condition1:
    if condition2:
        if condition3:
            do_something()

# Good - early returns
if not condition1:
    return
if not condition2:
    return
if not condition3:
    return
do_something()
```
