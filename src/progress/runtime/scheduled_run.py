"""scheduled-run consumer (PRFC 2026-08-31 phase 4c).

The serve tree mounts integrations + runner + this row; when
``schedule.cron`` (or the container's ``PROGRESS_SCHEDULE_CRON``
compatibility env) is non-empty, the row registers
``every(cron, runner.run_once)`` on the in-process scheduler. Empty cron
leaves the row mounted as a no-op — the tree shape is stable, the cadence
is data.

The row also owns run-cadence observability, cadence-agnostic by design
(the cron is a runtime config knob, never a baked-in "N times a day"):

* ``progress.schedule.expected_max_gap_seconds`` — largest gap between the
  next consecutive fires, exported at arm time. Alert rules divide by this
  instead of assuming a fixed daily count, so changing the cron changes the
  alert windows automatically.
* ``progress.pipeline.last_success_epoch`` — set after each successful run;
  staleness against the expected gap is the "pipeline silent" signal.
* Uptime Kuma push (``PROGRESS_KUMA_PUSH_URL``) — best-effort verdict push
  after every run with a per-push retention derived from the same expected
  gap; an empty URL disables the push entirely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from croniter import croniter

from progress.kernel import Entry

if TYPE_CHECKING:
    from progress.cli.outcome import RunOutcome
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)

SCHEDULE_CRON_ENV = "PROGRESS_SCHEDULE_CRON"
KUMA_PUSH_URL_ENV = "PROGRESS_KUMA_PUSH_URL"
KUMA_PUSH_MAX_RETENTION = 86_400
EXPECTED_GAP_FIRES = 8


def _cron_expression(cfg: CoreConfig) -> str:
    return cfg.schedule.cron or os.environ.get(SCHEDULE_CRON_ENV, "").strip()


def expected_max_gap_seconds(expression: str, *, fires: int = EXPECTED_GAP_FIRES) -> float:
    """Largest gap (s) between the next ``fires`` consecutive cron fires.

    Eight fires cover every 5-field cron pattern whose period repeats within
    a week (daily/hourly/weekly patterns all stabilize well before that).
    """
    iterator = croniter(expression, datetime.now(tz=UTC).astimezone())
    moments = [iterator.get_next(datetime) for _ in range(fires)]
    gaps = [(later - earlier).total_seconds() for earlier, later in pairwise(moments)]
    return max(gaps, default=0.0)


def kuma_push_retention_seconds(expression: str) -> int:
    """Push-monitor retention: twice the max gap plus a 30-minute grace.

    The multiplier leaves room for one missed/overlapping fire before kuma
    declares the monitor down, and is capped at kuma's 24h per-push limit.
    """
    return min(KUMA_PUSH_MAX_RETENTION, int(2 * expected_max_gap_seconds(expression) + 1_800))


def build_kuma_push_url(base_url: str, *, success: bool, message: str, retention: int) -> str:
    separator = "&" if "?" in base_url else "?"
    params = urlencode(
        {
            "status": "up" if success else "down",
            "msg": message[:500],
            "ping": retention,
        }
    )
    return f"{base_url}{separator}{params}"


async def push_run_verdict(base_url: str, *, success: bool, message: str, retention: int) -> bool:
    """Best-effort: kuma's own silence detection is the backstop, so a failed
    push is logged and swallowed, never raised into the run path."""
    import aiohttp  # noqa: PLC0415

    url = build_kuma_push_url(base_url, success=success, message=message, retention=retention)
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session, session.get(url) as response:
            await response.read()
            return 200 <= response.status < 300
    except Exception:
        logger.warning("kuma push failed (non-fatal; silence detection is the backstop)", exc_info=True)
        return False


def make_scheduled_run_entry() -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        from opentelemetry import metrics  # noqa: PLC0415

        expression = _cron_expression(ctx.config)
        if not expression:
            logger.info("schedule.cron empty; scheduled-run row idle")
            return

        max_gap = expected_max_gap_seconds(expression)
        retention = kuma_push_retention_seconds(expression)

        meter = metrics.get_meter("progress.scheduler")
        gap_gauge = meter.create_gauge(
            "progress.schedule.expected_max_gap_seconds",
            unit="s",
            description="Largest gap between consecutive cron fires (alert windows divide by this)",
        )
        gap_gauge.set(max_gap)
        success_gauge = meter.create_gauge(
            "progress.pipeline.last_success_epoch",
            unit="s",
            description="Unix epoch of the last successful scheduled run",
        )

        async def _trigger() -> None:
            logger.info("scheduled run starting (cron=%s)", expression)
            outcome: RunOutcome = await ctx.runner.run_once()
            success = outcome.exit_code == 0
            logger.info("scheduled run completed: exit_code=%s", outcome.exit_code)
            if success:
                success_gauge.set(datetime.now(tz=UTC).timestamp())
            push_url = os.environ.get(KUMA_PUSH_URL_ENV, "").strip()
            if push_url:
                await push_run_verdict(
                    push_url,
                    success=success,
                    message=f"scheduled run exit_code={outcome.exit_code}",
                    retention=retention,
                )

        dispose = ctx.scheduler.every(expression, _trigger, name="scheduled-run")
        ctx.effect(dispose)
        logger.info("scheduled-run armed: cron=%s (local time, per-entry mutex, no catch-up)", expression)

    return Entry(id="scheduled-run", plugin=_apply, inject=["config", "scheduler", "integrations", "runner"])


__all__ = [
    "EXPECTED_GAP_FIRES",
    "KUMA_PUSH_MAX_RETENTION",
    "KUMA_PUSH_URL_ENV",
    "SCHEDULE_CRON_ENV",
    "build_kuma_push_url",
    "expected_max_gap_seconds",
    "kuma_push_retention_seconds",
    "make_scheduled_run_entry",
    "push_run_verdict",
]
