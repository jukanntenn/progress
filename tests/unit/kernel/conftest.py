"""Kernel unit tests (spec 15 unit layer: pure asyncio, injected fakes, no IO).

The events catalog is process-global; tests redeclare entries with
``replace=True`` and this conftest restores the pre-test snapshot so the
pipeline catalog declared by ``progress.runtime.catalog`` survives.
"""

from __future__ import annotations

import pytest

from progress.kernel.events import catalog


@pytest.fixture(autouse=True)
def _preserve_event_catalog():
    snapshot = dict(catalog)
    yield
    catalog.clear()
    catalog.update(snapshot)
