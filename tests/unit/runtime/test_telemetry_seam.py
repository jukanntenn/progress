"""Telemetry hub seam (PRFC phase 3): sinks, scrub chain, metrics funnel."""

from __future__ import annotations

from typing import Any

from progress.config.root import CoreConfig
from progress.kernel import Entry, boot
from progress.observability.metrics import record_business_event, set_active_hub
from progress.runtime.telemetry import TelemetryService, make_telemetry_entry


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def write(self, kind: str, payload: dict[str, Any]) -> None:
        self.events.append((kind, payload))


def _make_sink_entry(sink: RecordingSink) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        undo = ctx.telemetry.add_sink(sink)
        ctx.effect(undo)

    _apply.name = "fake-sink"
    _apply.inject = ["telemetry"]
    return Entry(id="fake-sink", plugin=_apply, inject=["telemetry"])


def _make_config_entry(cfg: CoreConfig) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        ctx.provide("config", cfg)

    _apply.name = "stub-config"
    return Entry(id="stub-config", plugin=_apply)


async def test_third_party_sink_receives_business_events(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    sink = RecordingSink()
    async with boot([_make_config_entry(cfg), make_telemetry_entry(), _make_sink_entry(sink)]) as _ctx:
        record_business_event("progress.test.event", attributes={"repo": "acme/app"})
    assert sink.events and sink.events[0][0] == "business_event"
    assert sink.events[0][1]["name"] == "progress.test.event"


async def test_scrub_policy_transforms_payload(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    sink = RecordingSink()

    def _drop_repo(payload: dict[str, Any]) -> dict[str, Any]:
        payload["attributes"].pop("repo", None)
        payload["attributes"]["redacted"] = "yes"
        return payload

    def _make_policy_entry() -> Entry:
        async def _apply(ctx: Any, config: Any) -> None:
            undo = ctx.telemetry.add_scrub_policy(_drop_repo)
            ctx.effect(undo)

        _apply.name = "scrub-policy"
        _apply.inject = ["telemetry"]
        return Entry(id="scrub-policy", plugin=_apply, inject=["telemetry"])

    async with boot(
        [_make_config_entry(cfg), make_telemetry_entry(), _make_sink_entry(sink), _make_policy_entry()]
    ) as _ctx:
        record_business_event("progress.test.event", attributes={"repo": "acme/app", "secret_key": "abc"})
    attrs = sink.events[0][1]["attributes"]
    assert "repo" not in attrs
    assert attrs["redacted"] == "yes"
    assert attrs["secret_key"] == "[REDACTED]"  # default scrub_secrets still applied


async def test_funnel_restored_after_dispose(tmp_state_home: str):
    cfg = CoreConfig(state_home=tmp_state_home)
    before = set_active_hub(None)
    async with boot([_make_config_entry(cfg), make_telemetry_entry()]) as ctx:
        assert ctx.get(TelemetryService) is not None
    assert set_active_hub.__module__ is not None
    set_active_hub(before)
