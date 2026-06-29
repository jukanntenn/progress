from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..types import ParserType, R, is_parseable

if TYPE_CHECKING:
    from progress.config import AnalysisConfig


def noop(s: str) -> str:
    return s


class Analyzer(ABC):
    _config: AnalysisConfig

    def __init__(self, config: AnalysisConfig) -> None:
        self._config = config

    @property
    def timeout(self) -> int:
        return self._config.timeout

    @property
    def language(self) -> str:
        return self._config.language

    @property
    def provider(self) -> str:
        return self._config.provider

    @staticmethod
    def apply_parser(parser: ParserType[R], result: str) -> R:
        if is_parseable(parser):
            return parser.parse(result)
        return parser(result)

    @abstractmethod
    def analyze(
        self,
        content: str,
        prompt: str = "",
        parser: ParserType[R] = noop,
    ) -> R:
        pass
