"""Pydantic config schema for the ``proposal`` integration (spec 02).

Per spec 02 the proposal plugin config is::

    trackers = ["eip", "erc", "pep", "rfc", "dep"]

``trackers`` is set semantics (which built-in proposal kinds to enable). It
is a list because TOML has no set type; deduplication happens at load time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Built-in proposal kinds supported by this integration.
SUPPORTED_KINDS: frozenset[str] = frozenset({"eip", "erc", "pep", "rfc", "dep"})


class ProposalIntegrationConfig(BaseModel):
    """Top-level config for the ``proposal`` integration."""

    model_config = ConfigDict(extra="forbid")
    trackers: list[str] = Field(default_factory=list)

    @field_validator("trackers")
    @classmethod
    def _validate_trackers(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if item in seen:
                continue
            if item not in SUPPORTED_KINDS:
                raise ValueError(f"unsupported proposal kind: {item!r}. supported: {sorted(SUPPORTED_KINDS)}")
            seen.add(item)
            out.append(item)
        return out


__all__ = ["SUPPORTED_KINDS", "ProposalIntegrationConfig"]
