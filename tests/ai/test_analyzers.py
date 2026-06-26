from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from progress.ai.analyzers import create_analyzer
from progress.ai.analyzers.base import Analyzer, noop
from progress.ai.analyzers.claude_code import ClaudeCodeAnalyzer
from progress.ai.analyzers.codex import CodexAnalyzer
from progress.ai.analyzers.truncate import TruncateAnalyzer
from progress.config import AnalysisConfig
from progress.errors import AnalysisException


def _config(**overrides) -> AnalysisConfig:
    return AnalysisConfig(**overrides)


class TestAnalyzerApplyParser:
    def test_apply_parser_with_callable(self):
        result = Analyzer.apply_parser(int, "42")
        assert result == 42

    def test_apply_parser_with_parseable(self):
        class UpperParser:
            def parse(self, s: str) -> str:
                return s.upper()

        result = Analyzer.apply_parser(UpperParser(), "hello")
        assert result == "HELLO"

    def test_apply_parser_with_noop(self):
        result = Analyzer.apply_parser(noop, "text")
        assert result == "text"


class TestNoop:
    def test_returns_input(self):
        assert noop("anything") == "anything"


class TestTruncateAnalyzer:
    def test_truncates_content(self):
        analyzer = TruncateAnalyzer(_config(truncate_chars=5))
        result = analyzer.analyze("hello world")
        assert result == "hello"

    def test_returns_full_content_when_short(self):
        analyzer = TruncateAnalyzer(_config(truncate_chars=100))
        result = analyzer.analyze("hi")
        assert result == "hi"

    def test_applies_parser(self):
        analyzer = TruncateAnalyzer(_config(truncate_chars=5))
        result = analyzer.analyze("hello world", parser=list)
        assert result == ["h", "e", "l", "l", "o"]

    def test_empty_content(self):
        analyzer = TruncateAnalyzer(_config(truncate_chars=10))
        result = analyzer.analyze("")
        assert result == ""


class TestClaudeCodeAnalyzer:
    @patch("progress.ai.analyzers.claude_code.run_tool")
    def test_analyze_returns_parsed_stdout(self, mock_run_tool):
        mock_run_tool.return_value = "result text"
        analyzer = ClaudeCodeAnalyzer(_config())
        result = analyzer.analyze("some content", "my prompt")
        assert result == "result text"
        mock_run_tool.assert_called_once_with(
            "claude_code", "my prompt", "some content", config=analyzer._config
        )

    @patch("progress.ai.analyzers.claude_code.run_tool")
    def test_analyze_applies_parser(self, mock_run_tool):
        mock_run_tool.return_value = '{"key": "value"}'
        analyzer = ClaudeCodeAnalyzer(_config())
        result = analyzer.analyze("content", "prompt", parser=json.loads)
        assert result == {"key": "value"}

    @patch("progress.ai.analyzers.claude_code.run_tool")
    def test_propagates_analysis_exception(self, mock_run_tool):
        mock_run_tool.side_effect = AnalysisException("boom")
        analyzer = ClaudeCodeAnalyzer(_config())
        with pytest.raises(AnalysisException, match="boom"):
            analyzer.analyze("content", "prompt")


class TestCodexAnalyzer:
    @patch("progress.ai.analyzers.codex.run_tool")
    def test_analyze_returns_parsed_stdout(self, mock_run_tool):
        mock_run_tool.return_value = "result text"
        analyzer = CodexAnalyzer(_config())
        result = analyzer.analyze("some content", "my prompt")
        assert result == "result text"
        mock_run_tool.assert_called_once_with(
            "codex", "my prompt", "some content", config=analyzer._config
        )

    @patch("progress.ai.analyzers.codex.run_tool")
    def test_analyze_applies_parser(self, mock_run_tool):
        mock_run_tool.return_value = '{"key": "value"}'
        analyzer = CodexAnalyzer(_config())
        result = analyzer.analyze("content", "prompt", parser=json.loads)
        assert result == {"key": "value"}

    @patch("progress.ai.analyzers.codex.run_tool")
    def test_propagates_analysis_exception(self, mock_run_tool):
        mock_run_tool.side_effect = AnalysisException("boom")
        analyzer = CodexAnalyzer(_config())
        with pytest.raises(AnalysisException, match="boom"):
            analyzer.analyze("content", "prompt")


class TestCreateAnalyzer:
    def test_creates_claude_code_by_default(self):
        analyzer = create_analyzer(config=_config())
        assert isinstance(analyzer, ClaudeCodeAnalyzer)

    def test_creates_codex(self):
        analyzer = create_analyzer(config=_config(), provider="codex")
        assert isinstance(analyzer, CodexAnalyzer)

    def test_creates_truncate(self):
        analyzer = create_analyzer(config=_config(), provider="truncate")
        assert isinstance(analyzer, TruncateAnalyzer)

    def test_raises_on_unknown_provider(self):
        with pytest.raises(ValueError, match="Unsupported analyzer provider"):
            create_analyzer(config=_config(), provider="unknown")

    def test_uses_config_provider_when_none(self):
        analyzer = create_analyzer(config=_config(provider="truncate"))
        assert isinstance(analyzer, TruncateAnalyzer)

    def test_uses_config_provider_codex(self):
        analyzer = create_analyzer(config=_config(provider="codex"))
        assert isinstance(analyzer, CodexAnalyzer)
