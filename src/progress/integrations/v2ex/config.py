"""Pydantic config schema for the ``v2ex`` integration (spec 02 / spec v2ex §11).

Per spec v2ex §11 the v2ex integration owns only v2ex-specific knobs:

    base_url        = "https://www.v2ex.com"
    interest_profile = ""           # free-text; empty → disabled
    tabs            = ["jobs", "creative"]
    max_summaries   = 8             # 1..20, global top-K

Provider/model/api_key/base_url/language for the AI come from ``[core.analysis]``
(spec 08 single source); HTTP timeout/retry/UA/jitter are code constants
(spec 02 P4). Zero-config degrade: an empty ``interest_profile`` (or empty
``base_url``) disables the integration at ``setup`` time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: V2EX top-nav tab ids (verified against the live site nav). The tab page is
#: the only HTML endpoint that aggregates a tab's nodes in one request, so the
#: whitelist is the set of ids ``?tab=<id>`` accepts.
_SUPPORTED_TABS: frozenset[str] = frozenset(
    {"tech", "creative", "play", "apple", "jobs", "deals", "city", "qna", "hot", "all", "r2"}
)

#: Display metadata per tab: ``(Chinese name, emoji)``. V2EX is a Chinese site
#: so the canonical node/tab names are Chinese; these are code constants (not
#: i18n-translated) per spec v2ex §9/§11, mirroring how the site labels itself.
_TAB_META: dict[str, tuple[str, str]] = {
    "tech": ("技术", "💻"),
    "creative": ("创意", "💡"),
    "play": ("好玩", "🎮"),
    "apple": ("Apple", "🍎"),
    "jobs": ("酷工作", "🎯"),
    "deals": ("交易", "💰"),
    "city": ("城市", "🏙️"),
    "qna": ("问与答", "❓"),
    "hot": ("热门", "🔥"),
    "all": ("全部", "📋"),
    "r2": ("R2", "🗄️"),
}


class V2exIntegrationConfig(BaseModel):
    """Top-level config for the ``v2ex`` integration."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"ui_group": "integrations", "ui_order": 130},
    )

    base_url: str = Field(
        default="https://www.v2ex.com",
        title="V2EX Base URL",
        description="Base URL of V2EX. Point at a local pytest-httpserver in tests. Empty → disabled.",
        examples=["https://www.v2ex.com"],
    )
    interest_profile: str = Field(
        default="",
        title="兴趣画像",
        description=(
            "Free-text description of what you want (and do NOT want) to see. "
            "Semantic matching by the AI, so express nuanced/negative preferences freely. "
            "Empty → integration disabled (no profile = no filtering)."
        ),
        json_schema_extra={"format": "textarea"},
    )
    tabs: list[str] = Field(
        default=["jobs", "creative"],
        title="跟踪的板块",
        description=f"Which V2EX tabs to scan. Valid: {sorted(_SUPPORTED_TABS)}.",
        examples=[["jobs", "creative"]],
    )
    max_summaries: int = Field(
        default=8,
        ge=1,
        le=20,
        title="每轮最大总结数",
        description="Global top-K cap: bounds both body-fetch requests and report length.",
    )

    @field_validator("tabs")
    @classmethod
    def _validate_tabs(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("tabs must not be empty")
        seen: set[str] = set()
        out: list[str] = []
        for item in v:
            if item in seen:
                continue
            if item not in _SUPPORTED_TABS:
                raise ValueError(f"unsupported v2ex tab: {item!r}. supported: {sorted(_SUPPORTED_TABS)}")
            seen.add(item)
            out.append(item)
        return out


def tab_display(tab: str) -> tuple[str, str]:
    """Return ``(display_name, emoji)`` for a tab, defaulting to the raw id."""
    return _TAB_META.get(tab, (tab, "📋"))


__all__ = ["_SUPPORTED_TABS", "_TAB_META", "V2exIntegrationConfig", "tab_display"]
