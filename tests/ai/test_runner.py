from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from progress.ai.runner import (
    TransientAnalysisError,
    _is_transient,
    _run_once,
    run_tool,
)
from progress.config import AnalysisConfig
from progress.errors import AnalysisException


def _config(**overrides) -> AnalysisConfig:
    defaults = {"timeout": 600, "retries": 3, "retry_delay": 5}
    defaults.update(overrides)
    return AnalysisConfig(**defaults)


def _ok(stdout: str = "out", stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr
    )


def _fail(
    returncode: int = 1,
    stdout: str = "",
    stderr: str = "error",
) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestRunToolCommandBuilding:
    @patch("progress.ai.runner.subprocess.run")
    def test_returns_stdout_on_success(self, mock_run):
        mock_run.return_value = _ok(stdout="result text")
        assert (
            run_tool("claude_code", "prompt", "content", config=_config())
            == "result text"
        )

    @patch("progress.ai.runner.subprocess.run")
    def test_claude_code_command_and_input(self, mock_run):
        mock_run.return_value = _ok()
        run_tool("claude_code", "do thing", "content", config=_config())
        args, kwargs = mock_run.call_args
        assert args[0] == ["claude", "-p", "do thing"]
        assert kwargs["input"] == "content"
        assert kwargs["text"] is True
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False

    @patch("progress.ai.runner.subprocess.run")
    def test_codex_command(self, mock_run):
        mock_run.return_value = _ok()
        run_tool("codex", "do thing", "content", config=_config())
        args, _ = mock_run.call_args
        assert args[0] == [
            "codex",
            "exec",
            "--full-auto",
            "--skip-git-repo-check",
            "--color",
            "never",
            "do thing",
        ]

    @patch("progress.ai.runner.subprocess.run")
    def test_passes_none_input_for_empty_content(self, mock_run):
        mock_run.return_value = _ok()
        run_tool("claude_code", "prompt", "", config=_config())
        assert mock_run.call_args.kwargs["input"] is None

    @patch("progress.ai.runner.subprocess.run")
    def test_timeout_passed_from_config(self, mock_run):
        mock_run.return_value = _ok()
        run_tool("claude_code", "prompt", "content", config=_config(timeout=42))
        assert mock_run.call_args.kwargs["timeout"] == 42

    def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported AI tool provider"):
            run_tool("unknown", "prompt", "content", config=_config())


class TestIsTransient:
    @pytest.mark.parametrize(
        "stderr",
        [
            "rate limit exceeded",
            "HTTP 503 service unavailable",
            "server overloaded",
            "temporarily unavailable",
            "connection reset by peer",
            "ECONNRESET",
            "request timeout",
            "insufficient capacity",
        ],
    )
    def test_matches_known_markers(self, stderr):
        assert _is_transient(stderr) is True

    @pytest.mark.parametrize(
        "stderr",
        [
            "invalid API key",
            "command not found",
            "unexpected argument '--foo'",
            "authentication required",
        ],
    )
    def test_does_not_match_clean_stderr(self, stderr):
        assert _is_transient(stderr) is False

    def test_match_is_case_insensitive(self):
        assert _is_transient("RATE LIMIT") is True
        assert _is_transient("Overloaded") is True

    def test_empty_stderr_is_not_transient(self):
        assert _is_transient("") is False


class TestRunOnceClassification:
    @patch("progress.ai.runner.subprocess.run")
    def test_success_returns_stdout(self, mock_run):
        mock_run.return_value = _ok(stdout="hello")
        assert _run_once(["claude", "-p", "x"], "claude", "hello", 10) == "hello"

    @patch("progress.ai.runner.subprocess.run")
    def test_transient_nonzero_raises_transient_error(self, mock_run):
        mock_run.return_value = _fail(returncode=1, stderr="rate limit exceeded")
        with pytest.raises(TransientAnalysisError) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert exc_info.value.returncode == 1
        assert "rate limit" in exc_info.value.stderr_preview

    @patch("progress.ai.runner.subprocess.run")
    def test_permanent_nonzero_raises_analysis_exception(self, mock_run):
        mock_run.return_value = _fail(returncode=2, stderr="invalid api key")
        with pytest.raises(AnalysisException) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)
        assert "invalid api key" in str(exc_info.value)

    @patch("progress.ai.runner.subprocess.run")
    def test_timeout_is_transient(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=10)
        with pytest.raises(TransientAnalysisError):
            _run_once(["claude", "-p", "x"], "claude", "", 10)

    @patch("progress.ai.runner.subprocess.run")
    def test_file_not_found_is_permanent(self, mock_run):
        mock_run.side_effect = FileNotFoundError("claude")
        with pytest.raises(AnalysisException) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)
        assert "not found" in str(exc_info.value).lower()

    @patch("progress.ai.runner.subprocess.run")
    def test_oserror_is_permanent(self, mock_run):
        mock_run.side_effect = PermissionError("denied")
        with pytest.raises(AnalysisException) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)


class TestRetryBehavior:
    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_retries_transient_then_succeeds(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            _fail(returncode=1, stderr="overloaded"),
            _ok(stdout="done"),
        ]
        assert run_tool("claude_code", "p", "c", config=_config(retries=3)) == "done"
        assert mock_run.call_count == 2
        mock_sleep.assert_called_once_with(5)

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_exhausts_retries_on_persistent_transient(self, mock_run, mock_sleep):
        mock_run.return_value = _fail(returncode=1, stderr="rate limit")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_run.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_timeout_retried_then_succeeds(self, mock_run, mock_sleep):
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="claude", timeout=10),
            _ok(stdout="done"),
        ]
        assert (
            run_tool("claude_code", "p", "c", config=_config(retries=3, retry_delay=1))
            == "done"
        )
        assert mock_run.call_count == 2

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_permanent_failure_not_retried(self, mock_run, mock_sleep):
        mock_run.return_value = _fail(returncode=2, stderr="invalid api key")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_file_not_found_not_retried(self, mock_run, mock_sleep):
        mock_run.side_effect = FileNotFoundError("claude")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_retries_disabled_when_one(self, mock_run, mock_sleep):
        mock_run.return_value = _fail(returncode=1, stderr="rate limit")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=1))
        assert mock_run.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_backoff_grows_exponentially(self, mock_run, mock_sleep):
        mock_run.return_value = _fail(returncode=1, stderr="overloaded")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=4, retry_delay=5))
        sleeps = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleeps == [5, 10, 20]

    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_backoff_capped_at_max_delay(self, mock_run, mock_sleep):
        mock_run.return_value = _fail(returncode=1, stderr="overloaded")
        with pytest.raises(AnalysisException):
            run_tool("claude_code", "p", "c", config=_config(retries=6, retry_delay=40))
        sleeps = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleeps == [40, 60, 60, 60, 60]


class TestStderrHandling:
    @patch("progress.ai.runner.subprocess.run")
    def test_long_stderr_truncated_in_permanent_error(self, mock_run):
        mock_run.return_value = _fail(returncode=2, stderr="x" * 1000)
        with pytest.raises(AnalysisException) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert len(str(exc_info.value)) < 600

    @patch("progress.ai.runner.subprocess.run")
    def test_long_stderr_truncated_in_transient_error(self, mock_run):
        mock_run.return_value = _fail(returncode=1, stderr="rate limit " + "x" * 1000)
        with pytest.raises(TransientAnalysisError) as exc_info:
            _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert len(exc_info.value.stderr_preview) <= 500


class TestExhaustionLogging:
    @patch("progress.utils.time.sleep")
    @patch("progress.ai.runner.subprocess.run")
    def test_logs_error_with_provider_and_attempts(self, mock_run, mock_sleep, caplog):
        mock_run.return_value = _fail(returncode=1, stderr="rate limit exceeded")
        with caplog.at_level("ERROR"):
            with pytest.raises(AnalysisException):
                run_tool(
                    "claude_code", "p", "c", config=_config(retries=2, retry_delay=1)
                )
        messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            "claude" in m and "unavailable after 2 attempt" in m for m in messages
        )


class TestRealSubprocessSmoke:
    def test_real_success_returns_stdout(self):
        result = _run_once(
            [
                sys.executable,
                "-c",
                "import sys; print(sys.stdin.read().upper(), end='')",
            ],
            "python",
            "hello",
            10,
        )
        assert result == "HELLO"
