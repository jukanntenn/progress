"""scheduled-run consumer (PRFC 2026-08-31 phase 4c).

The serve tree mounts integrations + runner + this row; when
``schedule.cron`` (or the container's ``PROGRESS_SCHEDULE_CRON``
compatibility env) is non-empty, the row registers
``every(cron, runner.run_once)`` on the in-process scheduler. Empty cron
leaves the row mounted as a no-op — the tree shape is stable, the cadence
is data.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from progress.kernel import Entry

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)

SCHEDULE_CRON_ENV = "PROGRESS_SCHEDULE_CRON"


def _cron_expression(cfg: CoreConfig) -> str:
    return cfg.schedule.cron or os.environ.get(SCHEDULE_CRON_ENV, "").strip()


def make_scheduled_run_entry() -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        expression = _cron_expression(ctx.config)
        if not expression:
            logger.info("schedule.cron empty; scheduled-run row idle")
            return

        async def _trigger() -> None:
            logger.info("scheduled run starting (cron=%s)", expression)
            outcome = await ctx.runner.run_once()
            logger.info("scheduled run completed: exit_code=%s", outcome.exit_code)

        dispose = ctx.scheduler.every(expression, _trigger, name="scheduled-run")
        ctx.effect(dispose)
        logger.info("scheduled-run armed: cron=%s (local time, per-entry mutex, no catch-up)", expression)

    return Entry(id="scheduled-run", plugin=_apply, inject=["config", "scheduler", "integrations", "runner"])


__all__ = ["SCHEDULE_CRON_ENV", "make_scheduled_run_entry"]
