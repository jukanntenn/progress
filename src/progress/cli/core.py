"""CLI business orchestration entry point (spec 05; PRFC 2026-08-31 phase 2).

``run()`` is the e2e-callable thin entry: it boots the composition tree —
the shared base services, the integrations mounted through the ``@register``
shim, and the event-driven runner — and awaits one pipeline pass. All
orchestration lives in the runner's event catalog
(``progress.runtime.runner`` / ``progress.runtime.catalog``); the legacy
in-function producer/consumer plumbing and the pre-streaming aggregation
path (``run_notifications`` and friends) were deleted with this rewrite,
their behavior carried by the ``notification/build`` / ``notification/dispatch``
events.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from progress.kernel import boot as kernel_boot
from progress.runtime import compose_base
from progress.runtime.composition import effective_rows, rows_to_entries
from progress.runtime.integrations import make_integrations_entry
from progress.runtime.plugin_install import ensure_plugin_path
from progress.runtime.runner import make_runner_entry

if TYPE_CHECKING:
    from progress.cli.outcome import RunOutcome
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)


def make_run_base_entries(
    cfg: CoreConfig | None,
    *,
    config_path: str | None = None,
) -> list[Any]:
    if cfg is None:
        return []
    """The run profile's entry list (base services + integrations + runner)."""
    return [
        *compose_base(cfg, config_path=config_path, component="cli"),
        make_integrations_entry(),
        make_runner_entry(),
    ]


async def run(
    cfg: CoreConfig,
    *,
    config_path: str | None = None,
    trackers_only: bool = False,
) -> RunOutcome:
    """Run the full tracking pipeline.

    e2e tests call this directly: ``outcome = await run(cfg, config_path=...)``.
    """
    ensure_plugin_path(cfg.state_home)
    base_entries = make_run_base_entries(cfg, config_path=config_path)
    rows = effective_rows(base_entries, profile="run", cfg=cfg)
    async with kernel_boot(rows_to_entries(rows)) as kctx:
        return await kctx.runner.run_once(trackers_only=trackers_only)


__all__ = ["run"]
