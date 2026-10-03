"""AI seam (PRFC 2026-08-31 phase 3): analysis calls + concurrency, providers.

``ctx.ai`` is the analysis-call seam: ``ai-pydantic`` wraps the existing
pydantic-ai agent module with an instance-owned concurrency semaphore, and
``ai-replay`` is the deterministic replay provider for network-free tests.
Call sites do not migrate — the module-level ``run_extraction`` routes
through the active handle (same funnel pattern as telemetry), so the
existing per-module test patches keep working untouched.
"""

from __future__ import annotations

import asyncio
from collections import deque
import logging
from typing import TYPE_CHECKING, Any

from progress.cli.ai.agent import AI_CONCURRENCY, run_extraction_direct, set_active_ai
from progress.kernel import Definition, Entry

if TYPE_CHECKING:
    from progress.config.root import CoreConfig

logger = logging.getLogger(__name__)


class AiService(Definition):
    service_name = "ai"


class AiHandle:
    """ai-pydantic provider value: same transport, instance-owned semaphore."""

    def __init__(self, concurrency: int = AI_CONCURRENCY) -> None:
        self.semaphore = asyncio.Semaphore(concurrency)

    async def run_extraction(self, agent: Any, prompt: str, *, model: Any = None) -> Any:
        return await run_extraction_direct(agent, prompt, model=model, semaphore=self.semaphore)


class ReplayAiHandle:
    """ai-replay provider value: deterministic results, no network.

    Results are consumed in order; when the queue runs dry the last entry
    repeats (stable default for long component scenarios).
    """

    def __init__(self, results: list[Any] | None = None) -> None:
        self._queue = deque(results or [])
        self._last: Any = None
        self.calls: list[str] = []

    def queue(self, result: Any) -> None:
        self._queue.append(result)

    async def run_extraction(self, agent: Any, prompt: str, *, model: Any = None) -> Any:
        self.calls.append(prompt)
        if self._queue:
            self._last = self._queue.popleft()
        if self._last is None:
            raise AssertionError("replay AI handle has no queued result and no last entry to repeat")
        return self._last


def make_ai_entry(handle: AiHandle | ReplayAiHandle | None = None) -> Entry:
    """Provide ``ctx.ai`` and install it as the module funnel."""

    async def _apply(ctx: Any, config: Any) -> None:
        cfg: CoreConfig = ctx.config  # noqa: F841
        value = handle if handle is not None else AiHandle()
        previous = set_active_ai(value)
        ctx.provide(AiService, value)

        async def _teardown() -> None:
            set_active_ai(previous)

        ctx.effect(_teardown)

    return Entry(id="ai", plugin=_apply, inject=["config"])


__all__ = ["AiHandle", "AiService", "ReplayAiHandle", "make_ai_entry"]
