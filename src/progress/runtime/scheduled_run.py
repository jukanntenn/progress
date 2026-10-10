"""scheduled-run consumer (PRFC 2026-08-31 phase 4c).

The serve tree mounts integrations + runner + this row; it arms one scheduler
entry per schedule group. Groups are resolved at (re)arm time from the global
``schedule.cron`` (or the container's ``PROGRESS_SCHEDULE_CRON`` compatibility
env) plus every mounted integration's ``schedule_cron`` override: integrations
whose config schema declares the field and whose stored section sets it leave
the global group and run on their own cron (an override equal to the global
expression joins the global group). No cron and no overrides leaves the row
mounted as a no-op — the tree shape is stable, the cadence is data.

Arming re-runs on every ``integration/registry-changed`` event: integration
instances mount as child fibers that load one settle pass after this row, and
are added/removed at runtime by recompose, so an arm-time snapshot alone would
freeze whatever the registry happened to hold (issue #36 froze an empty one).

Each fire also checks the coverage invariant — every mounted integration must
belong to some armed group. A mounted-but-unscheduled integration means the
schedule drifted from the registry; the run is reported as failed (Kuma
``status=down``, no ``last_success`` refresh, a
``progress.schedule.coverage_drift`` business event) instead of succeeding
over zero integrations silently.

Run-cadence observability is per group (the cron is a runtime config knob,
never a baked-in "N times a day"):

* ``progress.schedule.expected_max_gap_seconds`` — largest gap between the
  next consecutive fires of each group's cron, exported at arm time with the
  group's cron and member names as attributes. Alert rules divide by this
  instead of assuming a fixed daily count, so changing a cron changes the
  alert windows automatically.
* ``progress.pipeline.last_success_epoch`` — set after each successful group
  run, attributed the same way; staleness against the expected gap is the
  "pipeline silent" signal.
* Uptime Kuma push (``PROGRESS_KUMA_PUSH_URL``) — best-effort verdict push
  after every group run with a per-push retention derived from that group's
  expected gap; the most frequent group dominates the single push monitor's
  silence window. An empty URL disables the push entirely.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
import logging
import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from croniter import croniter

from progress.kernel import Entry
from progress.observability import record_business_event
from progress.utils.cron import is_valid_cron_expression

if TYPE_CHECKING:
    from progress.cli.outcome import RunOutcome
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)

SCHEDULE_CRON_ENV = "PROGRESS_SCHEDULE_CRON"
KUMA_PUSH_URL_ENV = "PROGRESS_KUMA_PUSH_URL"
KUMA_PUSH_MAX_RETENTION = 86_400
EXPECTED_GAP_FIRES = 8


@dataclass
class ScheduleGroup:
    """One scheduler entry: a cron expression and the integrations it runs."""

    expression: str
    names: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return ",".join(self.names)

    def attributes(self) -> dict[str, str]:
        return {"schedule": self.expression, "integrations": self.label}


@dataclass
class _ArmState:
    """Mutable arm snapshot shared by re-arms, gauge callbacks, and triggers."""

    groups: list[ScheduleGroup] = field(default_factory=list)
    max_gaps: dict[str, float] = field(default_factory=dict)
    retentions: dict[str, int] = field(default_factory=dict)
    disposers: list[Callable[[], None]] = field(default_factory=list)
    closed: bool = False


def _cron_expression(cfg: CoreConfig) -> str:
    return cfg.schedule.cron or os.environ.get(SCHEDULE_CRON_ENV, "").strip()


async def resolve_schedule_overrides(instances: Iterable[Any]) -> dict[str, str]:
    """Per-integration cron overrides from DB sections, keyed by name.

    Only integrations whose config schema declares ``schedule_cron``
    participate — the field is the capability. An invalid stored value
    (schema downgrade, hand edit) degrades to inherit-global with a warning.
    """

    from progress.db import get_config  # noqa: PLC0415

    overrides: dict[str, str] = {}
    for instance in instances:
        schema = getattr(instance, "config_schema", None)
        fields = getattr(schema, "model_fields", None) or {}
        if "schedule_cron" not in fields:
            continue
        raw = await get_config(instance.name)
        value = raw.get("schedule_cron", "") if isinstance(raw, dict) else ""
        if not value:
            continue
        if not is_valid_cron_expression(value):
            logger.warning(
                "integration %s has invalid schedule_cron %r; inheriting global schedule",
                instance.name,
                value,
            )
            continue
        overrides[instance.name] = value
    return overrides


def resolve_schedule_groups(
    global_expression: str,
    names: Iterable[str],
    overrides: Mapping[str, str],
) -> list[ScheduleGroup]:
    """Group integrations by effective cron; overrides leave the global group.

    The global group is armed whenever the global cron is set (even with no
    members), preserving the pre-override idle-cron behaviour; an override
    equal to the global expression joins the global group instead of creating
    a duplicate entry.
    """

    groups: list[ScheduleGroup] = []
    by_expression: dict[str, ScheduleGroup] = {}
    if global_expression:
        inherited = ScheduleGroup(global_expression, [name for name in names if not overrides.get(name)])
        groups.append(inherited)
        by_expression[global_expression] = inherited
    for name in names:
        expression = overrides.get(name)
        if not expression:
            continue
        group = by_expression.get(expression)
        if group is not None:
            group.names.append(name)
        else:
            group = ScheduleGroup(expression, [name])
            by_expression[expression] = group
            groups.append(group)
    return groups


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
        from opentelemetry.metrics import CallbackOptions, Observation  # noqa: PLC0415

        state = _ArmState()
        last_success: dict[str, float] = {}
        rearm_lock = asyncio.Lock()

        async def _rearm() -> None:
            async with rearm_lock:
                if state.closed:
                    return
                for dispose in state.disposers:
                    dispose()
                state.disposers = []
                global_expression = _cron_expression(ctx.config)
                overrides = await resolve_schedule_overrides(ctx.integrations.instances)
                state.groups = resolve_schedule_groups(global_expression, ctx.integrations.names, overrides)
                if not state.groups:
                    logger.info("schedule.cron empty and no integration overrides; scheduled-run row idle")
                    state.max_gaps = {}
                    state.retentions = {}
                    return
                state.max_gaps = {g.expression: expected_max_gap_seconds(g.expression) for g in state.groups}
                state.retentions = {g.expression: kuma_push_retention_seconds(g.expression) for g in state.groups}
                for group in state.groups:
                    name = (
                        "scheduled-run"
                        if group.expression == global_expression
                        else f"scheduled-run[{group.expression}]"
                    )
                    state.disposers.append(ctx.scheduler.every(group.expression, _make_trigger(group), name=name))
                logger.info(
                    "scheduled-run armed: %s (local time, per-entry mutex, no catch-up)",
                    "; ".join(f"{g.expression} -> {g.label or '(none)'}" for g in state.groups),
                )

        def _make_trigger(group: ScheduleGroup) -> Any:
            async def _trigger() -> None:
                logger.info("scheduled run starting (cron=%s integrations=%s)", group.expression, group.label)
                outcome: RunOutcome = await ctx.runner.run_once(only=set(group.names))
                scheduled = {name for armed in state.groups for name in armed.names}
                drift = set(ctx.integrations.names) - scheduled
                if drift:
                    logger.error(
                        "schedule coverage drift: mounted integrations not scheduled: %s",
                        ",".join(sorted(drift)),
                    )
                    record_business_event(
                        "progress.schedule.coverage_drift",
                        attributes={"integrations": ",".join(sorted(drift)), "firing": group.expression},
                    )
                success = outcome.exit_code == 0 and not drift
                message = f"scheduled run integrations={group.label} exit_code={outcome.exit_code}"
                if drift:
                    message += f" unscheduled={','.join(sorted(drift))}"
                logger.info("scheduled run completed: integrations=%s exit_code=%s", group.label, outcome.exit_code)
                if success:
                    last_success[group.expression] = datetime.now(tz=UTC).timestamp()
                push_url = os.environ.get(KUMA_PUSH_URL_ENV, "").strip()
                if push_url:
                    await push_run_verdict(
                        push_url,
                        success=success,
                        message=message,
                        retention=state.retentions.get(group.expression, 0),
                    )

            return _trigger

        # Observable (callback) gauges, not sync ones: a sync gauge emits a
        # point only on .set(), so a once-per-boot set would go stale in the
        # stores and the telemetry-gap anchor would flap. Callbacks run on
        # every collection, so the series is continuously present while the
        # process lives. They read the mutable arm state so re-arms are
        # visible without re-registering the instruments.
        meter = metrics.get_meter("progress.scheduler")

        def _observe_gap(_options: CallbackOptions) -> list[Observation]:
            return [Observation(state.max_gaps[g.expression], attributes=g.attributes()) for g in state.groups]

        def _observe_last_success(_options: CallbackOptions) -> list[Observation]:
            return [
                Observation(last_success[g.expression], attributes=g.attributes())
                for g in state.groups
                if g.expression in last_success
            ]

        meter.create_observable_gauge(
            "progress.schedule.expected_max_gap_seconds",
            callbacks=[_observe_gap],
            unit="s",
            description="Largest gap between consecutive cron fires per schedule group (alert windows divide by this)",
        )
        meter.create_observable_gauge(
            "progress.pipeline.last_success_epoch",
            callbacks=[_observe_last_success],
            unit="s",
            description="Unix epoch of the last successful scheduled run per schedule group",
        )

        async def _on_registry_changed(_payload: Any) -> None:
            await _rearm()

        # The listener's own dispose rides this fiber's effects (ctx.on
        # registers it); it runs after _shutdown in the reversed unload order,
        # so late registry events during teardown hit the closed flag instead.
        _dispose_listener = ctx.on("integration/registry-changed", _on_registry_changed)

        def _shutdown() -> None:
            state.closed = True
            for dispose in state.disposers:
                dispose()

        ctx.effect(_shutdown)
        await _rearm()

    return Entry(id="scheduled-run", plugin=_apply, inject=["config", "scheduler", "integrations", "runner"])


__all__ = [
    "EXPECTED_GAP_FIRES",
    "KUMA_PUSH_MAX_RETENTION",
    "KUMA_PUSH_URL_ENV",
    "SCHEDULE_CRON_ENV",
    "ScheduleGroup",
    "build_kuma_push_url",
    "expected_max_gap_seconds",
    "kuma_push_retention_seconds",
    "make_scheduled_run_entry",
    "push_run_verdict",
    "resolve_schedule_groups",
    "resolve_schedule_overrides",
]
