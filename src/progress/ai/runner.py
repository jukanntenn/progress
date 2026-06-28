from __future__ import annotations

import logging
import subprocess
import time
from typing import TYPE_CHECKING

from progress.errors import AnalysisException
from progress.telemetry import get_tracer, record_analysis
from progress.utils import retry

if TYPE_CHECKING:
    from progress.config import AnalysisConfig

logger = logging.getLogger(__name__)

__all__ = ["run_tool"]

_STDERR_PREVIEW_LIMIT = 500
_MAX_DELAY = 60

_PROVIDER_BASE_ARGS: dict[str, list[str]] = {
    "claude_code": ["claude", "-p"],
    "codex": [
        "codex",
        "exec",
        "--full-auto",
        "--skip-git-repo-check",
        "--color",
        "never",
    ],
}

_TRANSIENT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "ratelimit",
    "overloaded",
    "503",
    "temporarily unavailable",
    "connection",
    "econnreset",
    "timeout",
    "capacity",
)


class TransientAnalysisError(AnalysisException):
    """A transient AI-tool failure that may succeed on retry.

    Subclasses AnalysisException so existing callers that catch
    AnalysisException are unaffected; the retry loop keys off this type
    internally to decide what is worth retrying.
    """

    def __init__(
        self,
        message: str,
        *,
        returncode: int | None,
        stderr_preview: str,
    ) -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr_preview = stderr_preview


def run_tool(
    provider: str,
    prompt: str,
    content: str,
    *,
    config: AnalysisConfig,
) -> str:
    if provider not in _PROVIDER_BASE_ARGS:
        raise ValueError(f"Unsupported AI tool provider: {provider}")

    base_args = _PROVIDER_BASE_ARGS[provider]
    executable = base_args[0]
    command = [*base_args, prompt]

    run_with_retry = retry(
        times=config.retries,
        initial_delay=config.retry_delay,
        backoff="exponential",
        exceptions=(TransientAnalysisError,),
        max_delay=_MAX_DELAY,
    )(_run_once)

    tracer = get_tracer("progress.ai")
    started = time.monotonic()
    ok = False
    failure_reason = ""
    try:
        with tracer.start_as_current_span(
            "ai.call",
            attributes={"ai.provider": provider, "ai.executable": executable},
        ):
            stdout = run_with_retry(command, executable, content, config.timeout)
        ok = True
        return stdout
    except TransientAnalysisError as e:
        failure_reason = "transient"
        logger.error(
            "AI tool '%s' unavailable after %d attempt(s) (last exit code %s): %s",
            executable,
            config.retries,
            e.returncode,
            e.stderr_preview,
        )
        raise
    except Exception:
        failure_reason = "error"
        raise
    finally:
        record_analysis(
            provider=provider,
            duration_s=time.monotonic() - started,
            ok=ok,
            reason=failure_reason,
        )


def _run_once(
    command: list[str],
    executable: str,
    content: str,
    timeout: int,
) -> str:
    logger.debug("Executing AI tool: %s", executable)
    try:
        completed = subprocess.run(
            command,
            input=content if content else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        raise TransientAnalysisError(
            f"AI tool '{executable}' timed out after {timeout}s",
            returncode=None,
            stderr_preview=str(e)[:_STDERR_PREVIEW_LIMIT],
        ) from e
    except FileNotFoundError as e:
        raise AnalysisException(
            f"AI tool '{executable}' not found; ensure it is installed and on PATH"
        ) from e
    except OSError as e:
        raise AnalysisException(
            f"AI tool '{executable}' could not be started: {e}"
        ) from e

    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    returncode = int(completed.returncode)

    if returncode == 0:
        return stdout

    stderr_preview = stderr.strip()[:_STDERR_PREVIEW_LIMIT]
    if _is_transient(stderr_preview):
        raise TransientAnalysisError(
            f"AI tool '{executable}' failed with exit code {returncode}: {stderr_preview}",
            returncode=returncode,
            stderr_preview=stderr_preview,
        )

    logger.error(
        "AI tool '%s' failed permanently with exit code %d: %s",
        executable,
        returncode,
        stderr_preview,
    )
    raise AnalysisException(
        f"AI tool '{executable}' failed with exit code {returncode}: {stderr_preview}"
    )


def _is_transient(stderr_text: str) -> bool:
    lowered = stderr_text.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)
