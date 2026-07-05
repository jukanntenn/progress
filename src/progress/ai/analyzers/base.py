from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..types import ParserType, R

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
    def apply_parser(parser: ParserType[R] | None, result: str) -> R:
        if parser is not None:
            return parser(result)
        return result  # ty: ignore[invalid-return-type]  # noop identity: returns the raw string unchanged. Only sound when R is str, which is the only case where the caller omits the parser.

    @abstractmethod
    def analyze[R](
        self,
        content: str,
        prompt: str = "",
        parser: ParserType[R] | None = None,
    ) -> R:
        pass
