"""Tortoise-ORM models package.

All models live here (or in their contrib packages) so that ``Tortoise.init``
can discover them via the ``modules`` mapping. The :func:`create_tables`
helper generates the schema (additive, ``IF NOT EXISTS``) and then runs the
idempotent historical migrations.
"""

from progress.db.models.app_config import AppConfig
from progress.db.models.base import BaseModel
from progress.db.models.batch import Batch
from progress.db.models.report import Report
from progress.db.models.repository import Repository

__all__ = [
    "AppConfig",
    "BaseModel",
    "Batch",
    "Report",
    "Repository",
    "create_tables",
    "migrate_database",
]


def __getattr__(name: str):
    if name == "create_tables":
        from progress.db import create_tables

        return create_tables
    if name == "migrate_database":
        from progress.db import migrate_database

        return migrate_database
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
