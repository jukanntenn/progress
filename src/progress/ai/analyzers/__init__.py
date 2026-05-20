from __future__ import annotations

from typing import TYPE_CHECKING

from progress.ai.analyzers.base import Analyzer
from progress.ai.analyzers.claude_code import ClaudeCodeAnalyzer
from progress.ai.analyzers.codex import CodexAnalyzer
from progress.ai.analyzers.truncate import TruncateAnalyzer

if TYPE_CHECKING:
    from progress.config import AnalysisConfig

__all__ = [
    "Analyzer",
    "ClaudeCodeAnalyzer",
    "CodexAnalyzer",
    "TruncateAnalyzer",
    "create_analyzer",
]


def create_analyzer(*, config: AnalysisConfig, provider: str | None = None) -> Analyzer:
    if provider is None:
        provider = config.provider
    if provider == "claude_code":
        return ClaudeCodeAnalyzer(config)
    if provider == "codex":
        return CodexAnalyzer(config)
    if provider == "truncate":
        return TruncateAnalyzer(config)
    raise ValueError(f"Unsupported analyzer provider: {provider}")
