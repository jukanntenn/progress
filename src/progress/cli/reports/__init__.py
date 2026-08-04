"""Report generation pipeline (spec 09).

Public API:
- :func:`run` — orchestrate the full pipeline (collect → render → aggregate →
  AI title → persist → publish).
- :class:`ReportOutcome` — structured result (success/partial/failed + errors).
"""

from __future__ import annotations

from progress.cli.reports.markpost import MarkpostClient, split_batches
from progress.cli.reports.pipeline import (
    BatchUrl,
    ReportContext,
    ReportOutcome,
    Section,
    collect_outcome,
    generate_title_summary,
    persist,
    publish_batches,
    render_aggregated,
    render_sections,
    run,
)

__all__ = [
    "BatchUrl",
    "MarkpostClient",
    "ReportContext",
    "ReportOutcome",
    "Section",
    "collect_outcome",
    "generate_title_summary",
    "persist",
    "publish_batches",
    "render_aggregated",
    "render_sections",
    "run",
    "split_batches",
]
