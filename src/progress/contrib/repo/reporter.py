"""Markdown report generator with i18n support."""

import logging
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

from ...consts import (
    TEMPLATE_AGGREGATED_REPORT,
    TEMPLATE_DISCOVERED_REPOS_REPORT,
    TEMPLATE_REPOSITORY_REPORT,
)
from ...i18n import gettext as _

logger = logging.getLogger(__name__)


def _escape_html(text: str) -> str:
    """Escape HTML tags in text.

    Args:
        text: Text to escape

    Returns:
        HTML-escaped text
    """
    return escape(text)


class MarkdownReporter:
    """Generate Markdown format reports with Jinja2 templates and i18n."""

    def __init__(self):
        """Initialize reporter with i18n support."""

        template_dir = Path(__file__).parent.parent.parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.jinja_env.globals["_"] = _
        self.jinja_env.filters["escape_html"] = _escape_html

    def generate_repository_report(
        self, report, timezone: ZoneInfo = ZoneInfo("UTC")
    ) -> str:
        """Generate single repository report.

        Args:
            report: RepositoryReport object with structured data
            timezone: Timezone for timestamps

        Returns:
            Rendered Markdown report
        """
        template = self.jinja_env.get_template(TEMPLATE_REPOSITORY_REPORT)
        return template.render(
            report=report,
            timezone=timezone,
        )

    def generate_aggregated_report(
        self,
        reports: list,
        total_commits: int,
        repo_statuses: dict[str, str],
        timezone: ZoneInfo = ZoneInfo("UTC"),
        batch_index: int = 0,
        total_batches: int = 1,
    ) -> str:
        """Generate aggregated report with status block.

        Args:
            reports: List of RepositoryReport objects
            total_commits: Total commit count across all repos
            repo_statuses: Dict mapping repo names to status ("success" | "failed" | "skipped")
            timezone: Timezone for timestamps
            batch_index: Current batch index (0-based)
            total_batches: Total number of batches

        Returns:
            Complete aggregated Markdown report
        """
        rendered_reports = []
        for report in reports:
            content = self.generate_repository_report(report, timezone)
            report.content = content
            rendered_reports.append(content)

        now = datetime.now(timezone)
        template = self.jinja_env.get_template(TEMPLATE_AGGREGATED_REPORT)
        return template.render(
            reports=reports,
            rendered_reports=rendered_reports,
            total_commits=total_commits,
            repo_statuses=repo_statuses,
            timezone=timezone,
            generation_time=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            iso_time=now.isoformat(),
            batch_index=batch_index,
            total_batches=total_batches,
        )

    def generate_discovered_repos_report(
        self, repos: list[dict], timezone: ZoneInfo = ZoneInfo("UTC")
    ) -> str:
        """Generate discovered repositories report.

        Args:
            repos: List of discovered repo dicts with fields:
                   owner_name, repo_name, repo_url, description,
                   readme_summary, readme_detail, discovered_at
            timezone: Timezone for timestamps

        Returns:
            Rendered Markdown report
        """
        now = datetime.now(timezone)
        template = self.jinja_env.get_template(TEMPLATE_DISCOVERED_REPOS_REPORT)
        return template.render(
            repos=repos,
            report_date=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        )
