"""AI seam (PRFC phase 3): funnel routing, replay provider, per-instance semaphore."""

from __future__ import annotations

from typing import Any

from progress.config.root import CoreConfig
from progress.kernel import Entry, boot
from progress.runtime.ai import AiHandle, AiService, ReplayAiHandle, make_ai_entry


def _config_entry(cfg: CoreConfig) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        ctx.provide("config", cfg)

    _apply.name = "stub-config"
    return Entry(id="stub-config", plugin=_apply)


async def test_active_handle_routes_run_extraction(tmp_state_home: str):
    from progress.cli.ai.agent import AnalysisResult, run_extraction  # noqa: PLC0415

    cfg = CoreConfig(state_home=tmp_state_home)
    replay = ReplayAiHandle(results=[AnalysisResult(summary="s", detail="d")])
    async with boot([_config_entry(cfg), make_ai_entry(replay)]) as ctx:
        assert ctx.get(AiService) is replay
        result = await run_extraction(agent=object(), prompt="analyze this")
    assert result.summary == "s"
    assert replay.calls == ["analyze this"]


async def test_funnel_restored_after_dispose(tmp_state_home: str):
    from progress.cli.ai.agent import set_active_ai  # noqa: PLC0415

    before = set_active_ai(None)
    cfg = CoreConfig(state_home=tmp_state_home)
    async with boot([_config_entry(cfg), make_ai_entry()]) as ctx:
        assert isinstance(ctx.get(AiService), AiHandle)
    from progress.cli.ai.agent import _active_ai  # noqa: PLC0415

    assert _active_ai is None
    set_active_ai(before)


async def test_replay_repeats_last_result(tmp_state_home: str):
    from progress.cli.ai.agent import AnalysisResult, run_extraction  # noqa: PLC0415

    cfg = CoreConfig(state_home=tmp_state_home)
    replay = ReplayAiHandle(results=[AnalysisResult(summary="one", detail="")])
    async with boot([_config_entry(cfg), make_ai_entry(replay)]) as _ctx:
        first = await run_extraction(agent=None, prompt="a")
        second = await run_extraction(agent=None, prompt="b")
    assert first.summary == "one"
    assert second.summary == "one"
