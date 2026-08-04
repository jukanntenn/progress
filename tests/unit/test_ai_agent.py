"""Unit tests for ``progress.cli.ai.agent`` (spec 08).

Tests the structured output extraction logic without making real model calls.
``_validate_with_repair`` is the core invariant: try direct JSON parse, fall
back to ``json_repair``, then raise ``ModelRetry``.

Pydantic AI's ``TestModel`` is used for the end-to-end agent test (spec 15
mock strategy).
"""

from __future__ import annotations

from pydantic import ValidationError
from pydantic_ai import ModelRetry
import pytest

from progress.cli.ai.agent import (
    AnalysisResult,
    TitleSummary,
    _validate_with_repair,
    build_model_string,
)
from progress.config.root import AnalysisConfig


class TestValidateWithRepair:
    def test_well_formed_json(self) -> None:
        out = _validate_with_repair(
            '{"summary": "s", "detail": "d"}',
            AnalysisResult,
        )
        assert out.summary == "s"
        assert out.detail == "d"

    def test_malformed_json_repaired(self) -> None:
        out = _validate_with_repair(
            '{"summary": "s", "detail": "d"',  # missing closing brace
            AnalysisResult,
        )
        assert out.summary == "s"
        assert out.detail == "d"

    def test_missing_field_after_repair_raises_model_retry(self) -> None:
        with pytest.raises(ModelRetry, match="could not be parsed"):
            _validate_with_repair('{"summary": "s"}', AnalysisResult)

    def test_completely_invalid_raises_model_retry(self) -> None:
        with pytest.raises(ModelRetry):
            _validate_with_repair("not json at all", AnalysisResult)

    def test_extra_field_silently_dropped(self) -> None:
        out = _validate_with_repair(
            '{"summary": "s", "detail": "d", "extra": "x"}',
            AnalysisResult,
        )
        assert out.summary == "s"
        assert out.detail == "d"
        assert not hasattr(out, "extra")


class TestBuildModelString:
    def test_no_provider_returns_none(self) -> None:
        cfg = AnalysisConfig(provider="", model="claude-sonnet-4")
        assert build_model_string(cfg) is None

    def test_no_model_returns_none(self) -> None:
        cfg = AnalysisConfig(provider="anthropic", model="")
        assert build_model_string(cfg) is None

    def test_provider_and_model(self) -> None:
        cfg = AnalysisConfig(provider="anthropic", model="claude-sonnet-4")
        assert build_model_string(cfg) == "anthropic:claude-sonnet-4"

    def test_openai_provider(self) -> None:
        cfg = AnalysisConfig(provider="openai", model="gpt-4o")
        assert build_model_string(cfg) == "openai:gpt-4o"


class TestAnalysisResult:
    def test_valid(self) -> None:
        r = AnalysisResult(summary="s", detail="d")
        assert r.summary == "s"
        assert r.detail == "d"

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AnalysisResult(summary="s")  # ty:ignore[missing-argument]


class TestTitleSummary:
    def test_valid(self) -> None:
        t = TitleSummary(title="Weekly Report", summary="covered 5 repos")
        assert t.title == "Weekly Report"
        assert t.summary == "covered 5 repos"

    def test_missing_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TitleSummary(title="t")  # ty:ignore[missing-argument]
