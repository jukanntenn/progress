# Storage Framework Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor report persistence to use protocol-based storage framework with multiple backends (filesystem, database, API) while preserving all existing functionality and maintaining zero changes to Peewee models.

**Architecture:** Protocol-based design using Python's `typing.Protocol` for clean separation between interface and implementations, with factory pattern for instantiation and composite decorator for database tracking.

**Tech Stack:** Python 3.12+, pytest (testing), pathlib (filesystem), peewee (ORM, existing), pydantic (configuration, existing), existing project infrastructure (errors, config, markpost client).

---

## Task 1: Verify Configuration Structure

**Files:**
- Read: `src/progress/config.py`

**Step 1: Check current config structure**

Run: `grep -n "class.*Config" src/progress/config.py`
Expected: List of existing config classes (MarkpostConfig, NotificationConfig, etc.)

**Step 2: Verify no ReportConfig exists yet**

Run: `grep -n "ReportConfig" src/progress/config.py`
Expected: No matches (ReportConfig not implemented yet)

**Step 3: Note where to add new config**

Look for pattern of existing config classes (they inherit from BaseSettings)
Expected: Found near line 50-100, config classes follow pattern

**Step 4: No commit yet** (this is verification only)

---

## Task 2: Add StorageType Enum and ReportConfig to Configuration

**Files:**
- Modify: `src/progress/config.py`
- Test: `tests/test_config.py` (append to existing file)

**Step 1: Write the failing test**

```python
# tests/test_config.py (append at end)
from progress.config import get_config, StorageType, ReportConfig


def test_report_config_defaults_to_auto():
    config = get_config()
    assert hasattr(config, "report")
    assert config.report.storage == StorageType.AUTO


def test_storage_type_enum_values():
    assert StorageType.DB == "db"
    assert StorageType.FILE == "file"
    assert StorageType.MARKPOST == "markpost"
    assert StorageType.AUTO == "auto"


def test_report_config_loads_from_toml():
    import tempfile
    import os
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        config_file = Path(tmpdir) / "config.toml"
        config_file.write_text("[report]\nstorage = \"file\"\n")

        # Temporarily set config file location
        original_env = os.environ.get("PROGRESS_CONFIG_FILE")
        os.environ["PROGRESS_CONFIG_FILE"] = str(config_file)

        try:
            from progress.config import get_config
            # Force reload by clearing cached config
            import importlib
            import progress.config
            importlib.reload(progress.config)
            from progress.config import get_config as get_new_config

            config = get_new_config()
            assert config.report.storage == StorageType.FILE
        finally:
            if original_env:
                os.environ["PROGRESS_CONFIG_FILE"] = original_env
            elif "PROGRESS_CONFIG_FILE" in os.environ:
                del os.environ["PROGRESS_CONFIG_FILE"]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_report_config_defaults_to_auto -v`
Expected: FAIL with "AttributeError: 'Config' object has no attribute 'report'" or ImportError for StorageType

**Step 3: Add StorageType enum and ReportConfig to config.py**

```python
# src/progress/config.py (add imports at top if not present)
from enum import Enum

# Add after existing imports, before first config class (around line 50)
class StorageType(str, Enum):
    DB = "db"
    FILE = "file"
    MARKPOST = "markpost"
    AUTO = "auto"


# Add ReportConfig class before Config class (around line 100-110)
class ReportConfig(BaseSettings):
    storage: StorageType = StorageType.AUTO


# Add report field to Config class (inside Config class, around line 150-160)
# Add this line with other field definitions:
report: ReportConfig = Field(default_factory=ReportConfig)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py::test_report_config_defaults_to_auto tests/test_config.py::test_storage_type_enum_values tests/test_config.py::test_report_config_loads_from_toml -v`
Expected: PASS (all 3 tests)

**Step 5: Verify backward compatibility**

Run: `uv run python -c "from progress.config import get_config; c = get_config(); print('Config loads:', hasattr(c, 'report'))"`
Expected: Output shows "Config loads: True"

**Step 6: Commit**

```bash
git add src/progress/config.py tests/test_config.py
git commit -m "feat(config): add storage type enum and report config

- Add StorageType enum (db, file, markpost, auto)
- Add ReportConfig with storage field defaulting to AUTO
- Backward compatible - existing configs work without changes
- Tests verify enum values and config loading

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Create Storage Protocol

**Files:**
- Create: `src/progress/storages/__init__.py` (empty for now)
- Create: `src/progress/storages/base.py`
- Test: `tests/storage/test_base.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_base.py
from progress.storages.base import Storage


def test_storage_protocol_requires_save_method():
    """Verify Storage protocol requires save method with correct signature."""

    class MockStorage:
        def save(self, title: str, body: str) -> str:
            return "mock-result"

    storage: Storage = MockStorage()
    result = storage.save("test title", "test body")
    assert result == "mock-result"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_base.py::test_storage_protocol_requires_save_method -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.base'"

**Step 3: Write minimal implementation**

```python
# src/progress/storages/base.py
from typing import Protocol


class Storage(Protocol):
    """Protocol for storage backends that persist report content."""

    def save(self, title: str, body: str) -> str:
        """Save report content and return identifier (path, URL, or ID).

        Args:
            title: Report title
            body: Report markdown content

        Returns:
            Identifier for saved content (file path, URL, or database ID)

        Raises:
            FeeberException: If save operation fails
        """
        ...
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_base.py::test_storage_protocol_requires_save_method -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/storage/test_base.py src/progress/storages/__init__.py src/progress/storages/base.py
git commit -m "feat(storages): add Storage protocol interface

- Define Storage protocol with save(title, body) -> str method
- Protocol enables pluggable storage backends
- Test verifies protocol compliance with mock implementation

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Implement FileStorage

**Files:**
- Create: `src/progress/storages/file.py`
- Test: `tests/storage/test_file.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_file.py
from pathlib import Path
from progress.storages.file import FileStorage


def test_file_storage_saves_content(tmp_path):
    """Verify FileStorage saves markdown content to filesystem."""
    storage = FileStorage(str(tmp_path))
    result = storage.save("Test Title", "Test Body")

    assert Path(result).exists()
    content = Path(result).read_text(encoding="utf-8")
    assert "# Test Title" in content
    assert "Test Body" in content


def test_file_storage_creates_directory_if_not_exists(tmp_path):
    """Verify FileStorage creates parent directories if needed."""
    dir_path = tmp_path / "subdir" / "nested"
    storage = FileStorage(str(dir_path))

    result = storage.save("Title", "Body")

    assert Path(result).parent.exists()
    assert Path(result).exists()


def test_file_storage_raises_on_permission_denied(tmp_path):
    """Verify FileStorage raises FeeberException on write errors."""
    from progress.errors import FeeberException

    storage = FileStorage(str(tmp_path))
    readonly_file = tmp_path / "readonly.md"
    readonly_file.write_text("readonly")
    readonly_file.chmod(0o444)

    # Try to save with existing readonly file path
    # This should trigger an error when trying to write
    import pytest

    # Create a subdirectory that can't be written to
    readonly_dir = tmp_path / "readonly_dir"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o444)

    storage_readonly = FileStorage(str(readonly_dir))
    with pytest.raises(FeeberException, match="Failed to write report"):
        storage_readonly.save("Title", "Body")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_file.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.file'"

**Step 3: Write minimal implementation**

```python
# src/progress/storages/file.py
import logging
from pathlib import Path
from time import time_ns

from progress.errors import FeeberException

logger = logging.getLogger(__name__)


class FileStorage:
    """Save report content to local filesystem."""

    def __init__(self, directory: str) -> None:
        """Initialize file storage with target directory.

        Args:
            directory: Directory path where reports will be saved
        """
        self._directory = Path(directory)

    def save(self, title: str, body: str) -> str:
        """Save report content as markdown file with timestamp name.

        Args:
            title: Report title (used as markdown heading)
            body: Report markdown content

        Returns:
            Absolute path to saved file

        Raises:
            FeeberException: If directory creation or file write fails
        """
        content = f"# {title}\n\n{body}"
        path = self._directory / f"{time_ns()}.md"
        logger.debug("Saving report to %s", path)

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            logger.error("Failed to write report to %s: %s", path, e)
            raise FeeberException(f"Failed to write report to {path}: {e}") from e

        return str(path)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_file.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add tests/storage/test_file.py src/progress/storages/file.py
git commit -m "feat(storages): add FileStorage backend

- Save markdown reports to filesystem with nanosecond timestamps
- Create parent directories automatically
- Raise FeeberException on write failures with context
- Tests verify content saving, directory creation, error handling

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Implement DBStorage

**Files:**
- Create: `src/progress/storages/db.py`
- Test: `tests/storage/test_db.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_db.py
from unittest.mock import patch
from progress.storages.db import DBStorage


def test_db_storage_saves_to_database():
    """Verify DBStorage delegates to Report.create_report()."""
    with patch("progress.storages.db.Report") as mock_report:
        mock_report.create_report.return_value = 123

        storage = DBStorage()
        result = storage.save("Test Title", "Test Body")

        assert result == "123"
        mock_report.create_report.assert_called_once_with(
            title="Test Title", body="Test Body"
        )
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_db.py::test_db_storage_saves_to_database -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.db'"

**Step 3: Verify Report.create_report exists**

Run: `grep -n "def create_report" src/progress/db.py`
Expected: Found function definition

Run: `grep -A 10 "def create_report" src/progress/db.py`
Expected: Function creates Report record and returns ID

**Step 4: Write minimal implementation**

```python
# src/progress/storages/db.py
import logging

from progress.db import create_report

logger = logging.getLogger(__name__)


class DBStorage:
    """Save report content to database using existing Report model."""

    def save(self, title: str, body: str) -> str:
        """Save report to database via create_report().

        Args:
            title: Report title
            body: Report markdown content

        Returns:
            Database record ID as string

        Raises:
            Propagates exceptions from create_report()
        """
        logger.debug("Saving report to database")
        report_id = create_report(title=title, body=body)
        return str(report_id)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_db.py::test_db_storage_saves_to_database -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/storage/test_db.py src/progress/storages/db.py
git commit -m "feat(storages): add DBStorage backend

- Wrap existing create_report() from db module
- Return database record ID as string
- Tests verify delegation to Report.create_report()

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Implement MarkpostStorage

**Files:**
- Create: `src/progress/storages/markpost.py`
- Test: `tests/storage/test_markpost.py`

**Step 1: Verify MarkpostClient exists**

Run: `grep -n "class MarkpostClient" src/progress/markpost.py`
Expected: Found class definition

Run: `grep -A 20 "class MarkpostClient" src/progress/markpost.py | grep "def upload"`
Expected: Found upload method

**Step 2: Write the failing test**

```python
# tests/storage/test_markpost.py
from unittest.mock import Mock
from progress.storages.markpost import MarkpostStorage


def test_markpost_storage_uploads_to_api():
    """Verify MarkpostStorage delegates to MarkpostClient.upload()."""
    mock_client = Mock()
    mock_client.upload.return_value = "https://example.com/post/123"

    storage = MarkpostStorage(mock_client)
    result = storage.save("Test Title", "Test Body")

    assert result == "https://example.com/post/123"
    mock_client.upload.assert_called_once_with(
        title="Test Title", body="Test Body"
    )
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_markpost.py::test_markpost_storage_uploads_to_api -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.markpost'"

**Step 4: Write minimal implementation**

```python
# src/progress/storages/markpost.py
import logging

from progress.markpost import MarkpostClient

logger = logging.getLogger(__name__)


class MarkpostStorage:
    """Save report content to external Markpost service."""

    def __init__(self, client: MarkpostClient) -> None:
        """Initialize with MarkpostClient instance.

        Args:
            client: Configured MarkpostClient for API communication
        """
        self._client = client

    def save(self, title: str, body: str) -> str:
        """Upload report content to Markpost service.

        Args:
            title: Report title
            body: Report markdown content

        Returns:
            URL of uploaded post

        Raises:
            Propagates exceptions from MarkpostClient.upload()
        """
        logger.info("Uploading report to Markpost: %s", title)
        return self._client.upload(title=title, body=body)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_markpost.py::test_markpost_storage_uploads_to_api -v`
Expected: PASS

**Step 6: Commit**

```bash
git add tests/storage/test_markpost.py src/progress/storages/markpost.py
git commit -m "feat(storages): add MarkpostStorage backend

- Wrap existing MarkpostClient for API uploads
- Return URL from upload response
- Tests verify delegation to client.upload()

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: Implement CombinedStorage

**Files:**
- Create: `src/progress/storages/combined.py`
- Test: `tests/storage/test_combined.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_combined.py
from unittest.mock import Mock
from progress.storages.combined import CombinedStorage


def test_combined_storage_saves_to_db_and_primary():
    """Verify CombinedStorage saves to DB first, then primary backend."""
    mock_db = Mock()
    mock_db.save.return_value = "123"

    mock_primary = Mock()
    mock_primary.save.return_value = "https://example.com/post/123"

    storage = CombinedStorage(mock_primary)
    storage._db = mock_db

    result = storage.save("Title", "Body")

    assert result == "https://example.com/post/123"
    mock_db.save.assert_called_once_with("Title", "Body")
    mock_primary.save.assert_called_once_with("Title", "Body")


def test_combined_storage_returns_primary_result():
    """Verify CombinedStorage returns primary backend result."""
    mock_db = Mock()
    mock_db.save.return_value = "123"

    mock_primary = Mock()
    mock_primary.save.return_value = "/path/to/file.md"

    storage = CombinedStorage(mock_primary)
    storage._db = mock_db

    result = storage.save("Title", "Body")

    assert result == "/path/to/file.md"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_combined.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.combined'"

**Step 3: Write minimal implementation**

```python
# src/progress/storages/combined.py
import logging

from .base import Storage
from .db import DBStorage

logger = logging.getLogger(__name__)


class CombinedStorage:
    """Decorator that saves to database and primary storage backend."""

    def __init__(self, primary: Storage) -> None:
        """Initialize with primary storage backend.

        Args:
            primary: Primary storage backend for content storage
        """
        self._primary = primary
        self._db = DBStorage()

    def save(self, title: str, body: str) -> str:
        """Save to database first (for tracking), then primary backend.

        Args:
            title: Report title
            body: Report markdown content

        Returns:
            Result from primary backend (path, URL, or ID)

        Raises:
            FeeberException: If database save fails
            Propagates exceptions from primary backend
        """
        logger.debug("Saving to combined storage (database + primary)")
        self._db.save(title, body)
        return self._primary.save(title, body)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_combined.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add tests/storage/test_combined.py src/progress/storages/combined.py
git commit -m "feat(storages): add CombinedStorage decorator

- Save to database first for tracking/history
- Delegate to primary backend for content storage
- Return primary backend result to caller
- Tests verify both storages called, primary result returned

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: Implement AutoStorage

**Files:**
- Create: `src/progress/storages/auto.py`
- Test: `tests/storage/test_auto.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_auto.py
from unittest.mock import patch, Mock
from progress.storages.auto import AutoStorage


def test_auto_storage_uses_markpost_when_configured():
    """Verify AutoStorage uses MarkpostStorage when markpost.base_url is set."""
    mock_config = Mock()
    mock_config.markpost.base_url = "https://example.com/markpost"
    mock_config.markpost.timeout = 30

    with patch("progress.storages.auto.get_config", return_value=mock_config):
        with patch("progress.storages.auto.MarkpostClient") as mock_client_cls:
            with patch("progress.storages.auto.MarkpostStorage") as mock_storage_cls:
                storage = AutoStorage()
                storage._storage.save("Title", "Body")

                mock_storage_cls.assert_called_once()


def test_auto_storage_falls_back_to_file_when_no_markpost():
    """Verify AutoStorage falls back to FileStorage when markpost.base_url is None."""
    mock_config = Mock()
    mock_config.markpost.base_url = None

    with patch("progress.storages.auto.get_config", return_value=mock_config):
        with patch("progress.storages.auto.FileStorage") as mock_storage_cls:
            storage = AutoStorage()
            storage._storage.save("Title", "Body")

            mock_storage_cls.assert_called_once_with("data/reports")
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_auto.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'progress.storages.auto'"

**Step 3: Write minimal implementation**

```python
# src/progress/storages/auto.py
import logging

from progress.config import get_config
from progress.markpost import MarkpostClient
from .file import FileStorage
from .markpost import MarkpostStorage

logger = logging.getLogger(__name__)


class AutoStorage:
    """Auto-select storage backend based on configuration."""

    def __init__(self) -> None:
        """Initialize by checking config and selecting appropriate backend."""
        config = get_config()
        markpost_url = getattr(config.markpost, "base_url", None)

        if markpost_url is not None:
            logger.debug("Using Markpost storage (configured)")
            client = MarkpostClient(
                url=str(markpost_url), timeout=config.markpost.timeout
            )
            self._storage = MarkpostStorage(client)
        else:
            logger.debug("Using file storage (no Markpost configured)")
            self._storage = FileStorage("data/reports")

    def save(self, title: str, body: str) -> str:
        """Save report using selected backend.

        Args:
            title: Report title
            body: Report markdown content

        Returns:
            Result from selected backend (path or URL)
        """
        return self._storage.save(title, body)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_auto.py -v`
Expected: PASS (both tests)

**Step 5: Commit**

```bash
git add tests/storage/test_auto.py src/progress/storages/auto.py
git commit -m "feat(storages): add AutoStorage with fallback

- Lazy initialization based on markpost.base_url configuration
- Use MarkpostStorage if configured, fall back to FileStorage
- Tests verify auto-selection logic for both cases

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: Implement Factory Function

**Files:**
- Modify: `src/progress/storages/__init__.py`
- Test: `tests/storage/test_factory.py`

**Step 1: Write the failing test**

```python
# tests/storage/test_factory.py
from unittest.mock import patch, Mock
from progress.config import StorageType
from progress.storages import get_storage


def test_get_storage_returns_db_storage_for_db():
    """Verify factory returns DBStorage when config.report.storage is DB."""
    mock_config = Mock()
    mock_config.report = Mock()
    mock_config.report.storage = StorageType.DB

    with patch("progress.storages.get_config", return_value=mock_config):
        with patch("progress.storages.DBStorage") as mock_db_storage:
            storage = get_storage()
            assert mock_db_storage.return_value == storage


def test_get_storage_returns_combined_with_file_for_file():
    """Verify factory returns CombinedStorage(FileStorage) for FILE."""
    mock_config = Mock()
    mock_config.report = Mock()
    mock_config.report.storage = StorageType.FILE

    with patch("progress.storages.get_config", return_value=mock_config):
        with patch("progress.storages.CombinedStorage") as mock_combined:
            with patch("progress.storages.FileStorage"):
                storage = get_storage()
                assert mock_combined.return_value == storage


def test_get_storage_returns_combined_with_auto_for_auto():
    """Verify factory returns CombinedStorage(AutoStorage) for AUTO."""
    mock_config = Mock()
    mock_config.report = Mock()
    mock_config.report.storage = StorageType.AUTO

    with patch("progress.storages.get_config", return_value=mock_config):
        with patch("progress.storages.CombinedStorage") as mock_combined:
            with patch("progress.storages.AutoStorage"):
                storage = get_storage()
                assert mock_combined.return_value == storage
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/storage/test_factory.py -v`
Expected: FAIL with "cannot import 'get_storage' from 'progress.storages'"

**Step 3: Write minimal implementation**

```python
# src/progress/storages/__init__.py
from progress.config import Storage as StorageType, get_config
from progress.errors import InvalidConfig
from progress.markpost import MarkpostClient
from .auto import AutoStorage
from .base import Storage
from .combined import CombinedStorage
from .db import DBStorage
from .file import FileStorage
from .markpost import MarkpostStorage


def get_storage() -> Storage:
    """Factory function that returns configured storage backend.

    Reads config.report.storage enum and returns appropriate storage instance:
    - DB: Database only
    - FILE: Filesystem + database tracking (via CombinedStorage)
    - MARKPOST: Markpost + database tracking (via CombinedStorage)
    - AUTO: Auto-select (Markpost if configured, else File) + database tracking

    Returns:
        Storage protocol instance

    Raises:
        InvalidConfig: If storage type is MARKPOST but markpost.base_url not configured
        InvalidConfig: If storage type is unknown
    """
    config = get_config()
    storage_type = config.report.storage

    if storage_type == StorageType.DB:
        return DBStorage()

    if storage_type == StorageType.MARKPOST:
        if config.markpost.base_url is None:
            raise InvalidConfig(
                "markpost.base_url is required for report.storage='markpost'"
            )
        client = MarkpostClient(
            url=str(config.markpost.base_url), timeout=config.markpost.timeout
        )
        return CombinedStorage(MarkpostStorage(client))

    if storage_type == StorageType.FILE:
        return CombinedStorage(FileStorage("data/reports"))

    if storage_type == StorageType.AUTO:
        return CombinedStorage(AutoStorage())

    raise InvalidConfig(f"Unknown storage type: {storage_type}")
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/storage/test_factory.py -v`
Expected: PASS (all 3 tests)

**Step 5: Commit**

```bash
git add tests/storage/test_factory.py src/progress/storages/__init__.py
git commit -m "feat(storages): add factory function get_storage()

- Configuration-driven storage instantiation
- Returns appropriate backend based on config.report.storage enum
- Raises InvalidConfig for missing required config
- Tests verify all storage types return correct instances

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Run All Storage Tests

**Files:**
- Test: All `tests/storage/*.py`

**Step 1: Run all storage tests**

Run: `uv run pytest tests/storage/ -v`
Expected: PASS (all 11 tests: 1 + 3 + 1 + 1 + 2 + 2 + 3)

**Step 2: Run with coverage**

Run: `uv run pytest tests/storage/ --cov=src/progress/storages --cov-report=term-missing`
Expected: High coverage (should be 100% or close to it)

**Step 3: No commit** (this is verification only)

---

## Task 11: Integrate Storage Framework with db.save_report()

**Files:**
- Modify: `src/progress/db.py`
- Test: `tests/test_db.py` (extend existing file)

**Step 1: Check current save_report implementation**

Run: `grep -A 20 "def save_report" src/progress/db.py`
Expected: Function signature and implementation using Report.create()

**Step 2: Write integration test**

```python
# tests/test_db.py (append at end)
from unittest.mock import patch, Mock
from progress.db import save_report


def test_save_report_uses_storage_framework():
    """Verify save_report() delegates to storage framework."""
    mock_storage = Mock()
    mock_storage.save.return_value = "test-result"

    with patch("progress.db.get_storage", return_value=mock_storage):
        result = save_report(title="Test", body="Body", repository_id=1,
                          current_commit="abc", previous_commit="def",
                          markpost_url=None)
        assert result == "test-result"
        mock_storage.save.assert_called_once_with("Test", "Body")
```

**Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_save_report_uses_storage_framework -v`
Expected: FAIL (old implementation doesn't use get_storage())

**Step 4: Modify save_report to use storage framework**

First, add import at top of `src/progress/db.py`:
```python
# Add with other imports at top
from .storages import get_storage
```

Then, modify the `save_report` function body. The function should still accept same parameters but now use storage:

```python
# Replace the body of save_report function
def save_report(
    title: str,
    body: str,
    repository_id: int | None = None,
    current_commit: str | None = None,
    previous_commit: str | None = None,
    markpost_url: str | None = None,
) -> str:
    """Save report to database and configured storage backend.

    Args:
        title: Report title
        body: Report markdown content
        repository_id: Optional repository foreign key
        current_commit: Current commit hash
        previous_commit: Previous commit hash
        markpost_url: Optional Markpost URL

    Returns:
        Result from storage backend (file path, URL, or database ID)

    Raises:
        FeeberException: If save operation fails
    """
    # Create Report record in database for tracking/history
    report_id = Report.create(
        repository=repository_id,
        current_commit=current_commit,
        previous_commit=previous_commit,
        content=body,
        markpost_url=markpost_url,
    ).id

    # Save to configured storage backend
    storage = get_storage()
    result = storage.save(title, body)

    # If storage backend returned a Markpost URL, update the Report
    if result.startswith("http"):
        Report.update_by_id(report_id, markpost_url=result)

    return str(result)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_save_report_uses_storage_framework -v`
Expected: PASS

**Step 6: Run full test suite to ensure no regressions**

Run: `uv run pytest tests/ -v`
Expected: All existing tests still pass

**Step 7: Commit**

```bash
git add src/progress/db.py tests/test_db.py
git commit -m "refactor(db): use storage framework for report persistence

- Replace direct Report.create() with storage framework
- Maintain backward compatibility - same function signature
- Update Report.markpost_url if storage returns URL
- All existing tests pass without modification

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 12: Final Verification and Quality Checks

**Files:**
- All storage framework files
- All test files

**Step 1: Type checking**

Run: `uv run mypy src/progress/storages/`
Expected: No errors or only acceptable ones (e.g., missing imports for Protocol)

**Step 2: Linting**

Run: `uv run ruff check src/progress/storages/`
Expected: No errors

Run: `uv run ruff format --check src/progress/storages/`
Expected: No changes needed

**Step 3: Run complete test suite**

Run: `uv run pytest tests/ -v --tb=short`
Expected: All PASS (including existing tests)

**Step 4: Manual smoke test**

Run: `uv run progress check` (if you have a configured repo)
Expected: Reports generated successfully, no errors

**Step 5: Verify database records**

Run: `sqlite3 data/progress.db "SELECT id, repository_id, markpost_url FROM reports ORDER BY id DESC LIMIT 5;"`
Expected: Report records created with all fields populated

**Step 6: Final commit if any adjustments needed**

If any code quality fixes were needed:
```bash
git add .
git commit -m "refactor(storages): complete storage framework implementation

- Protocol-based interface with pluggable backends
- FileStorage, DBStorage, MarkpostStorage implementations
- CombinedStorage decorator for database tracking
- AutoStorage with automatic fallback selection
- Factory function with configuration-driven instantiation
- Comprehensive test coverage (11 tests, 100% coverage)
- Zero changes to Peewee models - fully backward compatible
- Drop-in replacement for db.save_report()
- All existing tests pass without modification

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Implementation Notes

**Order matters:** Tasks are ordered to build incrementally:
1. Configuration setup (enables storage type selection)
2. Foundation (protocol)
3. Backends (file, db, markpost)
4. Decorators (combined, auto)
5. Factory (wiring it all together)
6. Integration (connecting to existing code)
7. Verification (testing and quality checks)

**TDD approach:** Each task follows Red-Green-Refactor:
1. Write failing test (Red)
2. Write minimal implementation (Green)
3. Verify test passes (confirm Green)
4. Commit (snapshot)

**Dependencies:**
- Tasks 3-8 are independent and can be done in any order (but recommended order follows logical dependencies)
- Task 9 (factory) depends on Tasks 3-8 being complete
- Task 11 (integration) depends on Task 9 being complete
- Task 12 (verification) must be last

**Testing references:**
- @python-testing for pytest patterns and TDD methodology
- @python-patterns for Pythonic code style
- @astral:ruff and @astral:ty for code quality checks

**Success criteria:**
- ✓ All 11 storage tests pass
- ✓ All existing tests pass without modification
- ✓ Type checking passes
- ✓ Linting passes
- ✓ Manual verification works
- ✓ Zero changes to Peewee models
- ✓ Backward compatible with existing code
