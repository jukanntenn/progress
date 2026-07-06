import json
import logging
import re
from typing import Any

import json_repair

from progress.ai import Analyzer
from progress.consts import TEMPLATE_ANALYSIS_PROMPT, TEMPLATE_README_ANALYSIS_PROMPT
from progress.errors import AnalysisException
from progress.i18n import gettext as _
from progress.telemetry import record_analysis_failure, report_error
from progress.templates import render

logger = logging.getLogger(__name__)


class AnalysisResultParser:
    def __call__(self, output: str) -> tuple[str, str]:
        return self.parse(output)

    def parse(self, output: str) -> tuple[str, str]:
        try:
            json_str = _extract_json(output)
            data = json.loads(json_str)
        except (AnalysisException, json.JSONDecodeError):
            data = json_repair.repair_json(output, return_objects=True)
            if not isinstance(data, dict):
                raise AnalysisException("Could not extract JSON from Claude output")
            logger.warning(
                "Claude output malformed or truncated; recovered via json_repair"
            )
        summary = data.get("summary", "")
        detail = data.get("detail", "")
        if not summary or not detail:
            raise AnalysisException(
                "Invalid JSON response: missing 'summary' or 'detail' field"
            )
        return summary, detail


def _extract_json(output: str) -> str:
    output = output.strip()
    match = re.search(r"\{[\s\S]*\}", output)
    if match:
        return match.group(0)
    raise AnalysisException("Could not extract JSON from Claude output")


async def analyze_diff(
    analyzer: Analyzer,
    repo_name: str,
    branch: str,
    diff: str,
    commit_messages: list[str],
    max_diff_length: int,
    language: str,
) -> tuple[str, str, bool, int, int]:
    original_length = len(diff)
    truncated = False

    if original_length > max_diff_length:
        truncated = True
        diff = diff[:max_diff_length]
        logger.warning(
            "Repository %s diff length (%d chars) exceeds limit (%d chars), truncated",
            repo_name,
            original_length,
            max_diff_length,
        )

    prompt = render(
        TEMPLATE_ANALYSIS_PROMPT,
        repo_name=repo_name,
        branch=branch,
        commit_messages=commit_messages,
        language=language,
        truncated=truncated,
        original_diff_length=original_length,
        analyzed_diff_length=len(diff),
    )

    logger.info("Analyzing code changes for %s...", repo_name)
    try:
        summary, detail = await analyzer.analyze(
            content=diff, prompt=prompt, parser=AnalysisResultParser()
        )
    except Exception as e:
        logger.warning("Code analysis failed: %s", e)
        provider = getattr(analyzer, "provider", "unknown")
        report_error(e, repo=repo_name, provider=provider, stage="diff_analysis")
        record_analysis_failure(provider=provider, reason="parse")
        summary = _("Code analysis unavailable")
        detail = _("Claude Code analysis failed or timed out. See logs for details.")

    return summary, detail, truncated, original_length, len(diff)


async def analyze_releases(
    analyzer: Analyzer,
    repo_name: str,
    branch: str,
    release_data: dict[str, Any],
    language: str,
) -> tuple[str, str]:
    releases = release_data.get("releases", [])
    is_first_check = len(releases) == 1
    prompt = render(
        "release_analysis_prompt.j2",
        repo_name=repo_name,
        branch=branch,
        release_data=release_data,
        is_first_check=is_first_check,
        language=language,
    )

    logger.info("Analyzing releases for %s...", repo_name)
    return await analyzer.analyze(content=prompt, parser=AnalysisResultParser())


async def analyze_readme(
    analyzer: Analyzer,
    repo_name: str,
    description: str | None,
    readme_content: str,
    language: str,
) -> tuple[str, str]:
    prompt = render(
        TEMPLATE_README_ANALYSIS_PROMPT,
        repo_name=repo_name,
        description=description,
        readme_content=readme_content,
        language=language,
    )

    logger.info("Analyzing README for %s...", repo_name)
    return await analyzer.analyze(content=prompt, parser=AnalysisResultParser())
