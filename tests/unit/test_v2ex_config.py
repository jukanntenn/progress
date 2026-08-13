"""Unit tests for V2exIntegrationConfig validation (spec v2ex §11)."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from progress.integrations.v2ex.config import (
    _SUPPORTED_TABS,
    V2exIntegrationConfig,
    tab_display,
)


class TestDefaults:
    def test_defaults(self) -> None:
        cfg = V2exIntegrationConfig()
        assert cfg.base_url == "https://www.v2ex.com"
        assert cfg.interest_profile == ""
        assert cfg.tabs == ["jobs", "creative"]
        assert cfg.max_summaries == 8


class TestTabsValidator:
    def test_rejects_empty_list(self) -> None:
        with pytest.raises(ValidationError):
            V2exIntegrationConfig(tabs=[])

    def test_rejects_unknown_tab(self) -> None:
        with pytest.raises(ValidationError):
            V2exIntegrationConfig(tabs=["bogus"])

    def test_dedupes_preserving_order(self) -> None:
        cfg = V2exIntegrationConfig(tabs=["jobs", "creative", "jobs", "tech"])
        assert cfg.tabs == ["jobs", "creative", "tech"]

    def test_accepts_all_supported(self) -> None:
        cfg = V2exIntegrationConfig(tabs=sorted(_SUPPORTED_TABS))
        assert set(cfg.tabs) == _SUPPORTED_TABS


class TestMaxSummariesBounds:
    def test_rejects_zero(self) -> None:
        with pytest.raises(ValidationError):
            V2exIntegrationConfig(max_summaries=0)

    def test_rejects_above_twenty(self) -> None:
        with pytest.raises(ValidationError):
            V2exIntegrationConfig(max_summaries=21)

    def test_accepts_bounds(self) -> None:
        assert V2exIntegrationConfig(max_summaries=1).max_summaries == 1
        assert V2exIntegrationConfig(max_summaries=20).max_summaries == 20


class TestExtraForbid:
    def test_rejects_unknown_field(self) -> None:
        with pytest.raises(ValidationError):
            V2exIntegrationConfig(unknown_field="x")  # type: ignore[call-arg]  # ty:ignore[unknown-argument]


class TestSchema:
    def test_ui_metadata(self) -> None:
        schema = V2exIntegrationConfig.model_json_schema()
        assert schema["ui_group"] == "integrations"
        assert schema["ui_order"] == 130

    def test_interest_profile_marked_textarea(self) -> None:
        schema = V2exIntegrationConfig.model_json_schema()
        assert schema["properties"]["interest_profile"]["format"] == "textarea"


class TestTabDisplay:
    def test_known_tab(self) -> None:
        assert tab_display("jobs") == ("酷工作", "🎯")
        assert tab_display("creative") == ("创意", "💡")

    def test_unknown_tab_fallback(self) -> None:
        assert tab_display("weird") == ("weird", "📋")
