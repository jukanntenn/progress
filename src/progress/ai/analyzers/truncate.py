from __future__ import annotations

from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
    from progress.config import AnalysisConfig

from ..types import ParserType, R
from .base import Analyzer, noop


class TruncateAnalyzer(Analyzer):
    def __init__(self, config: AnalysisConfig) -> None:
        super().__init__(config)
        self._max_chars: int = config.truncate_chars

    @override
    def analyze(
        self,
        content: str,
        prompt: str = "",
        parser: ParserType[R] = noop,
    ) -> R:
        truncated = content[: self._max_chars]
        return self.apply_parser(parser, truncated)
