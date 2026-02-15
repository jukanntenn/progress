from __future__ import annotations

import pytest

from progress.notification.utils import DiscoveredRepo


def test_discovered_repo_is_frozen() -> None:
    repo = DiscoveredRepo(name="owner/repo", url="https://github.com/owner/repo")

    with pytest.raises(Exception):
        repo.name = "changed"

