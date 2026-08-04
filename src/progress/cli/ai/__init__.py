"""AI analysis via Pydantic AI structured output extraction (spec 08).

Public API:
- :class:`AnalysisResult` / :class:`TitleSummary` — Pydantic output models.
- :func:`get_agent` — return the cached singleton Pydantic AI agent for a given
  output type (the model resolved once from live config; tests use
  ``agent.override(model=TestModel())`` to replace it).
- :func:`create_agent` — backward-compatible alias for :func:`get_agent`.
- :func:`build_model_string` — resolve ``AnalysisConfig`` to a model string.
- :func:`run_extraction` — run the agent and return the parsed result.

Prompt templates are co-located with their owning packages (spec 06):
reports-owned prompts live in :mod:`progress.cli.reports.prompts`, and each
integration owns its own ``prompts/`` directory. Use
:func:`progress.cli.reports.prompts.render_prompt` to render any of them.
"""

from __future__ import annotations

from progress.cli.ai.agent import (
    AnalysisResult,
    TitleSummary,
    build_model_string,
    create_agent,
    get_agent,
    run_extraction,
)

__all__ = [
    "AnalysisResult",
    "TitleSummary",
    "build_model_string",
    "create_agent",
    "get_agent",
    "run_extraction",
]
