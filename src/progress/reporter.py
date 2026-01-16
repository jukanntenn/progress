"""Markdown report generator with i18n support."""

import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader

from .consts import TEMPLATE_AGGREGATED_REPORT, TEMPLATE_REPOSITORY_REPORT
from .i18n import gettext as _

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """Generate Markdown format reports with Jinja2 templates and i18n."""

    def __init__(self):
        """Initialize reporter with i18n support."""

        template_dir = Path(__file__).parent / "templates"
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

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
            _=_,
        )

    def generate_aggregated_report(
        self,
        reports: list,
        total_commits: int,
        repo_statuses: dict[str, str],
        timezone: ZoneInfo = ZoneInfo("UTC"),
    ) -> str:
        """Generate aggregated report with status block.

        Args:
            reports: List of RepositoryReport objects
            total_commits: Total commit count across all repos
            repo_statuses: Dict mapping repo names to status ("success" | "failed" | "skipped")
            timezone: Timezone for timestamps

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
            _=_,
        )
