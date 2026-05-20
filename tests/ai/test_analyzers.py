from __future__ import annotations

from unittest.mock import patch

import pytest

from progress.ai.analyzers import create_analyzer
from progress.ai.analyzers.base import Analyzer, noop
from progress.ai.analyzers.claude_code import (
    ClaudeCodeAnalyzer,
)
from progress.ai.analyzers.claude_code import (
    CommandResult as ClaudeCommandResult,
)
from progress.ai.analyzers.codex import (
    CodexAnalyzer,
)
from progress.ai.analyzers.codex import (
    CommandResult as CodexCommandResult,
)
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
    @patch("progress.ai.analyzers.claude_code._run_command")
    def test_analyze_returns_stdout(self, mock_run):
        mock_run.return_value = ClaudeCommandResult(
            stdout="result text", stderr="", returncode=0
        )
        analyzer = ClaudeCodeAnalyzer(_config())
        result = analyzer.analyze("some content", "my prompt")
        assert result == "result text"
        mock_run.assert_called_once_with(
            ["claude", "-p", "my prompt"],
            input_text="some content",
            timeout=600,
        )

    @patch("progress.ai.analyzers.claude_code._run_command")
    def test_analyze_raises_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = ClaudeCommandResult(
            stdout="", stderr="error message", returncode=1
        )
        analyzer = ClaudeCodeAnalyzer(_config())
        with pytest.raises(AnalysisException, match="exit code 1"):
            analyzer.analyze("content", "prompt")

    @patch("progress.ai.analyzers.claude_code._run_command")
    def test_analyze_with_parser(self, mock_run):
        mock_run.return_value = ClaudeCommandResult(
            stdout='{"key": "value"}', stderr="", returncode=0
        )
        analyzer = ClaudeCodeAnalyzer(_config())
        import json

        result = analyzer.analyze("content", "prompt", parser=json.loads)
        assert result == {"key": "value"}

    @patch("progress.ai.analyzers.claude_code._run_command")
    def test_analyze_empty_content_passes_none(self, mock_run):
        mock_run.return_value = ClaudeCommandResult(
            stdout="ok", stderr="", returncode=0
        )
        analyzer = ClaudeCodeAnalyzer(_config())
        analyzer.analyze("", "prompt")
        mock_run.assert_called_once_with(
            ["claude", "-p", "prompt"],
            input_text=None,
            timeout=600,
        )


class TestCodexAnalyzer:
    @patch("progress.ai.analyzers.codex._run_command")
    def test_analyze_returns_stdout(self, mock_run):
        mock_run.return_value = CodexCommandResult(
            stdout="result text", stderr="", returncode=0
        )
        analyzer = CodexAnalyzer(_config())
        result = analyzer.analyze("some content", "my prompt")
        assert result == "result text"
        mock_run.assert_called_once_with(
            [
                "codex",
                "exec",
                "--full-auto",
                "--skip-git-repo-check",
                "--color",
                "never",
                "my prompt",
            ],
            input_text="some content",
            timeout=600,
        )

    @patch("progress.ai.analyzers.codex._run_command")
    def test_analyze_raises_on_nonzero_returncode(self, mock_run):
        mock_run.return_value = CodexCommandResult(
            stdout="", stderr="Codex command failed", returncode=1
        )
        analyzer = CodexAnalyzer(_config())
        with pytest.raises(AnalysisException, match="exit code 1"):
            analyzer.analyze("content", "prompt")

    @patch("progress.ai.analyzers.codex._run_command")
    def test_analyze_truncates_long_stderr_in_error(self, mock_run):
        long_stderr = "x" * 1000
        mock_run.return_value = CodexCommandResult(
            stdout="", stderr=long_stderr, returncode=2
        )
        analyzer = CodexAnalyzer(_config())
        with pytest.raises(AnalysisException) as exc_info:
            analyzer.analyze("content", "prompt")
        assert len(exc_info.value.args[0]) < 600

    @patch("progress.ai.analyzers.codex._run_command")
    def test_analyze_with_parser(self, mock_run):
        mock_run.return_value = CodexCommandResult(
            stdout='{"key": "value"}', stderr="", returncode=0
        )
        analyzer = CodexAnalyzer(_config())
        import json

        result = analyzer.analyze("content", "prompt", parser=json.loads)
        assert result == {"key": "value"}

    @patch("progress.ai.analyzers.codex._run_command")
    def test_analyze_empty_content_passes_none(self, mock_run):
        mock_run.return_value = CodexCommandResult(stdout="ok", stderr="", returncode=0)
        analyzer = CodexAnalyzer(_config())
        analyzer.analyze("", "prompt")
        mock_run.assert_called_once_with(
            [
                "codex",
                "exec",
                "--full-auto",
                "--skip-git-repo-check",
                "--color",
                "never",
                "prompt",
            ],
            input_text=None,
            timeout=600,
        )


class TestRunCommand:
    def test_returns_command_result(self):
        from progress.ai.analyzers.claude_code import _run_command

        result = _run_command(["echo", "hello"], input_text=None, timeout=10)
        assert result.returncode == 0
        assert result.stdout.strip() == "hello"

    def test_captures_stderr(self):
        from progress.ai.analyzers.claude_code import _run_command

        result = _run_command(
            ["python", "-c", "import sys; sys.stderr.write('err')"],
            input_text=None,
            timeout=10,
        )
        assert result.stderr == "err"

    def test_raises_on_timeout(self):
        from progress.ai.analyzers.claude_code import _run_command

        with pytest.raises(AnalysisException, match="Command failed"):
            _run_command(
                ["python", "-c", "import time; time.sleep(10)"],
                input_text=None,
                timeout=1,
            )

    def test_raises_on_nonexistent_command(self):
        from progress.ai.analyzers.claude_code import _run_command

        with pytest.raises(AnalysisException, match="Command failed"):
            _run_command(
                ["nonexistent_command_xyz"],
                input_text=None,
                timeout=10,
            )

    def test_passes_input_text(self):
        from progress.ai.analyzers.claude_code import _run_command

        result = _run_command(
            ["python", "-c", "import sys; print(sys.stdin.read().upper(), end='')"],
            input_text="hello",
            timeout=10,
        )
        assert result.returncode == 0
        assert result.stdout == "HELLO"


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
