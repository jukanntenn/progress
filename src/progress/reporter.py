"""Markdown report generator."""

import logging
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """Generate Markdown format reports."""

    def __init__(self):
        """Initialize reporter (no templates needed)."""
        pass

    def generate_aggregated_report(
        self, reports: list, timezone: ZoneInfo = ZoneInfo("UTC")
    ) -> str:
        """Generate aggregated report by concatenating repository reports.

        Args:
            reports: List of RepositoryReport objects
            timezone: Timezone object (unused, kept for compatibility)

        Returns:
            Complete aggregated Markdown report
        """
        return "\n\n---\n\n".join(report.content for report in reports)
