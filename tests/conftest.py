"""Shared pytest fixtures.

Async DB tests use the ``test_db`` fixture (asyncio_mode="auto" means ``async
def`` test functions need no decorator). Each test gets a fresh temporary
SQLite database, initializes tortoise-orm, creates the schema, yields, and
closes the connections on teardown.
"""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from progress.db import close_db, create_tables, init_db


@pytest_asyncio.fixture
async def test_db(tmp_path: Path) -> AsyncIterator[str]:
    db_path = tmp_path / "test.db"
    await init_db(str(db_path))
    await create_tables()
    try:
        yield str(db_path)
    finally:
        await close_db()
