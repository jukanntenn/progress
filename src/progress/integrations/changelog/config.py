"""Pydantic config schema for the ``changelog`` integration (spec 02).

Per spec 02 the changelog plugin config looks like::

    [[trackers]]
    name = "Vite"
    url = "https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"
    parser_type = "auto"      # "auto" | "markdown_heading" | "html_generic"
    enabled = true
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ParserType = Literal["auto", "markdown_heading", "html_generic"]

_LEGACY_PARSER_TYPES: dict[str, str] = {"html_chinese_version": "auto"}


class ChangelogItemConfig(BaseModel):
    """Single changelog tracker entry."""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(
        title="Name",
        description="Display name for this changelog source.",
        examples=["Vite"],
    )
    url: str = Field(
        title="URL",
        description="Raw text URL of the changelog.",
        examples=["https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"],
    )
    parser_type: ParserType = Field(
        default="auto",
        title="Parser Type",
        description="How to parse the changelog content.",
    )
    enabled: bool = Field(
        default=True,
        title="Enabled",
        description="Whether to track this changelog source.",
    )

    @field_validator("parser_type", mode="before")
    @classmethod
    def _normalize_legacy_parser_type(cls, v: object) -> object:
        if isinstance(v, str):
            return _LEGACY_PARSER_TYPES.get(v, v)
        return v


class ChangelogIntegrationConfig(BaseModel):
    """Top-level config for the ``changelog`` integration."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "integrations", "ui_order": 100},
    )
    trackers: list[ChangelogItemConfig] = Field(
        default_factory=list,
        title="Tracked Changelogs",
        description="List of changelog sources to monitor.",
    )


__all__ = [
    "ChangelogIntegrationConfig",
    "ChangelogItemConfig",
    "ParserType",
]
