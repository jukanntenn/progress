"""Markdown 报告生成器"""

import logging
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .analyzer import AnalysisResult

logger = logging.getLogger(__name__)


class MarkdownReporter:
    """生成 Markdown 格式的报告"""

    def __init__(self):
        """初始化 Jinja2 环境"""
        template_dir = Path(__file__).parent / "templates"
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate_repository_report(
        self,
        repo_name: str,
        repo_url: str,
        branch: str,
        current_commit: str,
        previous_commit: str,
        commit_count: int,
        analysis: AnalysisResult,
        commit_messages: list[str],
    ) -> str:
        """生成单个仓库的 Markdown 报告（用于汇总）

        Returns:
            Markdown 内容
        """
        template = self.env.get_template("repository_report.j2")

        return template.render(
            repo_name=repo_name,
            repo_url=repo_url,
            branch=branch,
            current_commit=current_commit,
            previous_commit=previous_commit,
            commit_count=commit_count,
            analysis=analysis,
            commit_messages=commit_messages,
        )

    def generate_aggregated_report(self, reports: list) -> str:
        """生成汇总报告

        Args:
            reports: 报告列表，每个报告包含 repo_name, content 等

        Returns:
            完整的汇总 Markdown 报告
        """
        template = self.env.get_template("aggregated_report.j2")

        return template.render(
            reports=reports,
            generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            iso_time=datetime.now().isoformat(),
        )

    def generate(
        self,
        repo_name: str,
        repo_url: str,
        branch: str,
        current_commit: str,
        previous_commit: str,
        commit_count: int,
        analysis: AnalysisResult,
        commit_messages: list[str],
    ) -> str:
        """生成 Markdown 报告（单个仓库完整版，已弃用）

        Returns:
            Markdown 内容
        """
        template = self.env.get_template("standalone_report.j2")

        return template.render(
            repo_name=repo_name,
            repo_url=repo_url,
            branch=branch,
            current_commit=current_commit,
            previous_commit=previous_commit,
            commit_count=commit_count,
            analysis=analysis,
            commit_messages=commit_messages,
            generation_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            iso_time=datetime.now().isoformat(),
        )
