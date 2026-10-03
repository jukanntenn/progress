"""i18n entry: set the active locale from merged config."""

from __future__ import annotations

from progress.kernel import Entry
from progress.utils.i18n import set_locale


def make_i18n_entry() -> Entry:
    async def _apply(ctx, config) -> None:
        set_locale(ctx.config.language)

    return Entry(id="i18n", plugin=_apply, inject=["config"])
