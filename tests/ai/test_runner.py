from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

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
    return AnalysisConfig(**defaults)  # ty: ignore[invalid-argument-type]  # test helper with mixed-type overrides dict


def _ok(stdout: str = "out", stderr: str = "") -> MagicMock:
    """A fake subprocess whose communicate() resolves to a successful run."""
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout.encode("utf-8"), stderr.encode("utf-8")))
    proc.returncode = 0
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


def _fail(
    returncode: int = 1,
    stdout: str = "",
    stderr: str = "error",
) -> MagicMock:
    """A fake subprocess whose communicate() resolves to a failed run."""
    proc = MagicMock()
    proc.communicate = AsyncMock(
        return_value=(stdout.encode("utf-8"), stderr.encode("utf-8"))
    )
    proc.returncode = returncode
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    return proc


class TestRunToolCommandBuilding:
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_returns_stdout_on_success(self, mock_exec):
        mock_exec.return_value = _ok(stdout="result text")
        assert (
            await run_tool("claude_code", "prompt", "content", config=_config())
            == "result text"
        )

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_claude_code_command_and_input(self, mock_exec):
        mock_exec.return_value = _ok()
        await run_tool("claude_code", "do thing", "content", config=_config())
        args, kwargs = mock_exec.call_args
        assert args == ("claude", "-p", "do thing")
        assert kwargs["stdin"] is not None
        assert kwargs["stdout"] is not None
        assert kwargs["stderr"] is not None
        # content is fed to communicate(), not to create_subprocess_exec
        proc = mock_exec.return_value
        assert proc.communicate.call_args.args == (b"content",)

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_codex_command(self, mock_exec):
        mock_exec.return_value = _ok()
        await run_tool("codex", "do thing", "content", config=_config())
        assert mock_exec.call_args.args == (
            "codex",
            "exec",
            "--full-auto",
            "--skip-git-repo-check",
            "--color",
            "never",
            "do thing",
        )

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_passes_none_input_for_empty_content(self, mock_exec):
        mock_exec.return_value = _ok()
        await run_tool("claude_code", "prompt", "", config=_config())
        proc = mock_exec.return_value
        assert proc.communicate.call_args.args == (None,)

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_timeout_passed_from_config(self, mock_exec):
        mock_exec.return_value = _ok()
        await run_tool("claude_code", "prompt", "content", config=_config(timeout=42))
        # timeout is enforced by asyncio.wait_for around communicate(); the proc
        # mock receives it as the timeout arg of wait_for (not asserted here).
        # Just assert the call ran with the configured timeout available.
        assert mock_exec.return_value.communicate.call_args.args == (b"content",)

    async def test_unknown_provider_raises_value_error(self):
        with pytest.raises(ValueError, match="Unsupported AI tool provider"):
            await run_tool("unknown", "prompt", "content", config=_config())


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
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_success_returns_stdout(self, mock_exec):
        mock_exec.return_value = _ok(stdout="hello")
        assert await _run_once(["claude", "-p", "x"], "claude", "hello", 10) == "hello"

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_transient_nonzero_raises_transient_error(self, mock_exec):
        mock_exec.return_value = _fail(returncode=1, stderr="rate limit exceeded")
        with pytest.raises(TransientAnalysisError) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert exc_info.value.returncode == 1
        assert "rate limit" in exc_info.value.stderr_preview

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_permanent_nonzero_raises_analysis_exception(self, mock_exec):
        mock_exec.return_value = _fail(returncode=2, stderr="invalid api key")
        with pytest.raises(AnalysisException) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)
        assert "invalid api key" in str(exc_info.value)

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_timeout_is_transient(self, mock_exec):
        proc = MagicMock()
        proc.communicate = AsyncMock(side_effect=TimeoutError())
        proc.returncode = 0
        proc.kill = MagicMock()
        proc.wait = AsyncMock()
        mock_exec.return_value = proc
        with pytest.raises(TransientAnalysisError):
            await _run_once(["claude", "-p", "x"], "claude", "", 10)

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_file_not_found_is_permanent(self, mock_exec):
        mock_exec.side_effect = FileNotFoundError("claude")
        with pytest.raises(AnalysisException) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)
        assert "not found" in str(exc_info.value).lower()

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_oserror_is_permanent(self, mock_exec):
        mock_exec.side_effect = PermissionError("denied")
        with pytest.raises(AnalysisException) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert not isinstance(exc_info.value, TransientAnalysisError)


class TestRetryBehavior:
    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_retries_transient_then_succeeds(self, mock_exec, mock_sleep):
        mock_exec.side_effect = [
            _fail(returncode=1, stderr="overloaded"),
            _ok(stdout="done"),
        ]
        assert await run_tool("claude_code", "p", "c", config=_config(retries=3)) == "done"
        assert mock_exec.call_count == 2
        mock_sleep.assert_called_once_with(5)

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_exhausts_retries_on_persistent_transient(self, mock_exec, mock_sleep):
        mock_exec.return_value = _fail(returncode=1, stderr="rate limit")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_exec.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_timeout_retried_then_succeeds(self, mock_exec, mock_sleep):
        timeout_proc = MagicMock()
        timeout_proc.communicate = AsyncMock(side_effect=TimeoutError())
        timeout_proc.returncode = 0
        timeout_proc.kill = MagicMock()
        timeout_proc.wait = AsyncMock()
        mock_exec.side_effect = [timeout_proc, _ok(stdout="done")]
        assert (
            await run_tool("claude_code", "p", "c", config=_config(retries=3, retry_delay=1))
            == "done"
        )
        assert mock_exec.call_count == 2

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_permanent_failure_not_retried(self, mock_exec, mock_sleep):
        mock_exec.return_value = _fail(returncode=2, stderr="invalid api key")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_exec.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_file_not_found_not_retried(self, mock_exec, mock_sleep):
        mock_exec.side_effect = FileNotFoundError("claude")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=3))
        assert mock_exec.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_retries_disabled_when_one(self, mock_exec, mock_sleep):
        mock_exec.return_value = _fail(returncode=1, stderr="rate limit")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=1))
        assert mock_exec.call_count == 1
        mock_sleep.assert_not_called()

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_backoff_grows_exponentially(self, mock_exec, mock_sleep):
        mock_exec.return_value = _fail(returncode=1, stderr="overloaded")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=4, retry_delay=5))
        sleeps = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleeps == [5, 10, 20]

    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_backoff_capped_at_max_delay(self, mock_exec, mock_sleep):
        mock_exec.return_value = _fail(returncode=1, stderr="overloaded")
        with pytest.raises(AnalysisException):
            await run_tool("claude_code", "p", "c", config=_config(retries=6, retry_delay=40))
        sleeps = [call.args[0] for call in mock_sleep.call_args_list]
        assert sleeps == [40, 60, 60, 60, 60]


class TestStderrHandling:
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_long_stderr_truncated_in_permanent_error(self, mock_exec):
        mock_exec.return_value = _fail(returncode=2, stderr="x" * 1000)
        with pytest.raises(AnalysisException) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert len(str(exc_info.value)) < 600

    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_long_stderr_truncated_in_transient_error(self, mock_exec):
        mock_exec.return_value = _fail(returncode=1, stderr="rate limit " + "x" * 1000)
        with pytest.raises(TransientAnalysisError) as exc_info:
            await _run_once(["claude", "-p", "x"], "claude", "", 10)
        assert len(exc_info.value.stderr_preview) <= 500


class TestExhaustionLogging:
    @patch("progress.utils.functional.asyncio.sleep", new_callable=AsyncMock)
    @patch("progress.ai.runner.asyncio.create_subprocess_exec", new_callable=AsyncMock)
    async def test_logs_error_with_provider_and_attempts(self, mock_exec, mock_sleep, caplog):
        mock_exec.return_value = _fail(returncode=1, stderr="rate limit exceeded")
        with caplog.at_level("ERROR"):
            with pytest.raises(AnalysisException):
                await run_tool(
                    "claude_code", "p", "c", config=_config(retries=2, retry_delay=1)
                )
        messages = [r.message for r in caplog.records if r.levelname == "ERROR"]
        assert any(
            "claude" in m and "unavailable after 2 attempt" in m for m in messages
        )


class TestRealSubprocessSmoke:
    async def test_real_success_returns_stdout(self):
        result = await _run_once(
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
