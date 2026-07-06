from __future__ import annotations

from typing import override

from ..runner import run_tool
from ..types import ParserType, R
from .base import Analyzer


class ClaudeCodeAnalyzer(Analyzer):
    @override
    async def analyze[R](
        self,
        content: str,
        prompt: str = "",
        parser: ParserType[R] | None = None,
    ) -> R:
        stdout = await run_tool("claude_code", prompt, content, config=self._config)
        return self.apply_parser(parser, stdout)
