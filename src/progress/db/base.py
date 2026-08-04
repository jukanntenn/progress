"""Tortoise-ORM abstract base model.

Per spec 03, models use the **bare** field declaration style (no annotations)
which keeps ty/pyright happy without ``# type: ignore`` markers. Models that
declare ``updated_at`` get auto-refresh on save.
"""

from typing import Any, override

from tortoise.models import Model

from progress.utils.timezone import now_utc


class BaseModel(Model):
    """Abstract base. Models that declare ``updated_at`` get auto-refresh on save."""

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

    class Meta:
        abstract = True


__all__ = ["BaseModel"]
