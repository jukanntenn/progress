from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, override

from progress.errors import AnalysisException

if TYPE_CHECKING:
    pass

from ..types import ParserType, R
from .base import Analyzer, noop

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandResult:
    stdout: str
    stderr: str
    returncode: int


class CodexAnalyzer(Analyzer):
    _STDERR_PREVIEW_LIMIT = 500

    @override
    def analyze(
        self,
        content: str,
        prompt: str = "",
        parser: ParserType[R] = noop,
    ) -> R:
        result = _run_command(
            [
                "codex",
                "exec",
                "--full-auto",
                "--skip-git-repo-check",
                "--color",
                "never",
                prompt,
            ],
            input_text=content if content else None,
            timeout=self._config.timeout,
        )
        if result.returncode != 0:
            stderr_preview = result.stderr.strip()[: self._STDERR_PREVIEW_LIMIT]
            logger.error(
                "Codex failed with exit code %d: %s",
                result.returncode,
                stderr_preview,
            )
            raise AnalysisException(
                f"Codex failed with exit code {result.returncode}: {stderr_preview}"
            )

        return self.apply_parser(parser, result.stdout)


def _run_command(
    args: list[str],
    *,
    input_text: str | None,
    timeout: int,
) -> CommandResult:
    logger.debug("Executing command: %s", args[0] if args else "empty")
    try:
        result = subprocess.run(
            args,
            input=input_text,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error("Command failed: %s", e)
        raise AnalysisException(f"Command failed: {e}") from e

    return CommandResult(
        stdout=result.stdout or "",
        stderr=result.stderr or "",
        returncode=int(result.returncode),
    )
