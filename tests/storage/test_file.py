from pathlib import Path

import pytest

from progress.errors import ProgressException
from progress.storages.file import FileStorage


def test_file_storage_saves_content(tmp_path):
    storage = FileStorage()
    result = storage.save("Test Title", "Test Body", tmp_path)

    saved = Path(result)
    assert saved.exists()
    content = saved.read_text(encoding="utf-8")
    assert "# Test Title" in content
    assert "Test Body" in content


def test_file_storage_creates_directory_if_not_exists(tmp_path):
    directory = tmp_path / "subdir" / "nested"
    storage = FileStorage()
    result = storage.save("Title", "Body", directory)

    saved = Path(result)
    assert saved.parent.exists()
    assert saved.exists()


def test_file_storage_raises_on_permission_denied(tmp_path):
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555)

    storage = FileStorage()
    with pytest.raises(ProgressException, match="Failed to write report"):
        storage.save("Title", "Body", readonly_dir)


def test_file_storage_uses_seconds_timestamp(tmp_path):
    storage = FileStorage()
    result = storage.save("Title", "Body", tmp_path)

    filename = Path(result).stem
    assert len(filename) == 10  # seconds timestamp is 10 digits
