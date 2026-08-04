"""Unit-test-scoped fixtures: fresh in-memory Tortoise DB per test (spec 15).

Scoped to ``tests/unit/`` only so component/api/e2e layers keep their own
DB setup (component tests shadow ``db`` with a file-based fixture; api tests
initialise Tortoise via the FastAPI lifespan and must not be double-init'd by
an autouse fixture).
"""

from __future__ import annotations

import pytest
from tortoise import Tortoise

from progress.db.tortoise_config import build_tortoise_config


@pytest.fixture
def db_url() -> str:
    return "sqlite://:memory:?journal_mode=WAL&synchronous=NORMAL&busy_timeout=5000&foreign_keys=ON&cache_size=-64000"


@pytest.fixture(autouse=True)
async def db(db_url: str):
    await Tortoise.init(
        config=build_tortoise_config(db_url),
        _enable_global_fallback=True,
    )
    await Tortoise.generate_schemas()
    try:
        yield
    finally:
        await Tortoise.close_connections()
