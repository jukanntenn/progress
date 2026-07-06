"""Tortoise-ORM base model with updated_at auto-refresh on save."""

from datetime import datetime
from typing import Any, override

from tortoise.models import Model

from progress.utils.timezone import now_utc


class BaseModel(Model):
    """Abstract base model.

    Mirrors the prior peewee BaseModel: models that declare an ``updated_at``
    field have it auto-refreshed on every save of a persisted instance, and
    when ``update_fields`` is given the refreshed timestamp is injected so it
    is actually persisted.
    """

    @classmethod
    def _has_updated_at(cls) -> bool:
        return "updated_at" in cls._meta.fields

    @override
    async def save(
        self,
        using_db: Any = None,
        update_fields: Any = None,
        force_create: bool = False,
        force_update: bool = False,
    ) -> None:
        if self._has_updated_at() and self.pk is not None:
            self.updated_at = now_utc()  # type: ignore[attr-defined]
            if update_fields is not None and "updated_at" not in update_fields:
                update_fields = [*update_fields, "updated_at"]
        await super().save(
            using_db=using_db,
            update_fields=update_fields,
            force_create=force_create,
            force_update=force_update,
        )

    @override
    async def delete(self, using_db: Any = None) -> None:
        await super().delete(using_db=using_db)

    class Meta:
        abstract = True


__all__ = ["BaseModel", "now_utc", "datetime"]
