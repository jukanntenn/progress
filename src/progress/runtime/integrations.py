"""integrations entry: discovery + the ``@register`` shim + instance registry.

Every integration — built-in or discovered via entry_points — mounts as its
own child fiber through the shim: the five-hook protocol is preserved
(third parties load unchanged), configuration stays instance-loaded from DB
sections, and the fiber per instance is the mechanism that later phases use
for multi-instance composition and surgical reload.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from progress.integrations.base import Components, Integration
from progress.integrations.registry import discover_integrations
from progress.kernel import Definition, Entry


class IntegrationsService(Definition):
    service_name = "integrations"


@dataclass
class IntegrationRegistry:
    """The instance registry service value (``ctx.integrations``)."""

    instances: list[Integration] = field(default_factory=list)

    def add(self, instance: Integration) -> None:
        self.instances.append(instance)

    def remove(self, instance: Integration) -> None:
        self.instances.remove(instance)

    def by_name(self, name: str) -> Integration | None:
        return next((i for i in self.instances if i.name == name), None)

    @property
    def names(self) -> list[str]:
        return [i.name for i in self.instances]


def make_integration_plugin(cls: Any) -> Any:
    """Wrap one Integration-protocol class into a kernel plugin (the shim)."""

    async def _apply(ctx: Any, config: Any) -> None:
        instance = cls()
        await instance.setup(Components(cfg=ctx.config, session=ctx.http, ai=ctx.get("ai")))
        registry = ctx.integrations
        registry.add(instance)

        async def _teardown() -> None:
            registry.remove(instance)
            await instance.teardown()

        ctx.effect(_teardown)

        async def _build_listener(payload: Any) -> None:
            if payload.name != instance.name:
                return
            produced = await instance.build_notification(result=payload.result, reports=payload.reports)
            payload.out.extend(produced)
            return

        ctx.on("notification/build", _build_listener)

    integration_name = getattr(cls, "name", None) or getattr(cls, "__name__", "integration")
    return {
        "apply": _apply,
        "inject": ["config", "http", "integrations", "ai"],
        "name": f"integration-{integration_name}",
    }


def make_integrations_entry() -> Entry:
    """The discovery row: re-discovery rides the recompose diff (L3 activation).

    Discovery runs at factory time only to take a fingerprint of the
    discovered names, which rides on the row's config; ``recompose`` compares
    configs, so installing or removing a plugin changes the fingerprint and
    restarts this row — the apply below then re-discovers and remounts the
    instances. Discovery itself stays inside apply so a broken plugin cannot
    break composition (it fails this fiber, not the tree).
    """
    fingerprint = ",".join(sorted(discover_integrations()))

    async def _apply(ctx: Any, config: Any) -> None:
        ctx.provide(IntegrationsService, IntegrationRegistry())
        for name, cls in discover_integrations().items():
            ctx.plugin(make_integration_plugin(cls), name=f"integration-{name}")

    return Entry(id="integrations", plugin=_apply, inject=["config", "http"], config={"entry_points": fingerprint})


__all__ = [
    "IntegrationRegistry",
    "IntegrationsService",
    "make_integration_plugin",
    "make_integrations_entry",
]
