"""AI analysis helpers for the repo integration (spec repo §8).

All AI analysis goes through the unified Pydantic AI interface (spec 08).
Three analyses:

- commit diff analysis → ``analysis_prompt.j2`` (diff + commit messages)
- release analysis → ``release_analysis_prompt.j2`` (release data)
- README analysis → ``readme_analysis_prompt.j2`` (repo metadata + README)

Failure is downgraded per spec repo §8.4 — each analysis returns an
``AnalysisResult`` with fallback text on AI failure; tracking never blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

from progress.cli.ai import (
    AnalysisResult,
    build_model_string,
    get_agent,
    run_extraction,
)
from progress.cli.reports.prompts import render_prompt
from progress.config.root import AnalysisConfig
from progress.errors import ProgressException
from progress.observability import record_business_event, report_severe

logger = logging.getLogger(__name__)

MAX_DIFF_LENGTH: int = 100_000
MAX_README_LENGTH: int = 50_000


@dataclass
class TruncatedDiff:
    """Result of truncating a diff text per spec repo §8.3."""

    text: str
    truncated: bool
    original_length: int
    analyzed_length: int


def truncate_diff(
    diff_text: str,
    *,
    max_length: int = MAX_DIFF_LENGTH,
    source: str = "commit",
) -> TruncatedDiff:
    """Truncate ``diff_text`` to ``max_length`` chars (spec repo §8.3).

    ``source`` labels which diff kind was truncated (``"commit"`` / ``"release"``
    / ``"proposal"``) so the WARNING carries enough context to attribute it —
    the bare ``diff truncated: N -> M chars`` line was unattributable in
    production logs (same span_id across a whole repo run, no repo/tag field).
    """
    original = len(diff_text)
    if original <= max_length:
        return TruncatedDiff(
            text=diff_text,
            truncated=False,
            original_length=original,
            analyzed_length=original,
        )
    truncated_text = diff_text[:max_length]
    logger.warning(
        "%s diff truncated: %d -> %d chars",
        source,
        original,
        max_length,
    )
    return TruncatedDiff(
        text=truncated_text,
        truncated=True,
        original_length=original,
        analyzed_length=max_length,
    )


def truncate_readme(readme: str) -> tuple[str, bool]:
    """Truncate README to ``MAX_README_LENGTH`` (spec repo §7.3)."""
    if len(readme) <= MAX_README_LENGTH:
        return readme, False
    return readme[:MAX_README_LENGTH], True


async def _run_analysis(
    prompt: str,
    cfg: AnalysisConfig,
    *,
    analysis_kind: str = "",
    empty_marker: str | None = None,
) -> AnalysisResult | None:
    """Invoke the AI agent and parse the result.

    Returns ``None`` if AI is not configured (downstream callers substitute
    fallback text). Raises only on AI failure (caught by callers).

    ``analysis_kind`` (``"commit_diff"`` / ``"release"`` / ``"readme"``) and
    ``empty_marker`` (the exact substring the prompt emits when a key variable
    is missing, e.g. ``"No release notes provided."``) feed observability: the
    prompt length and an ``inputs_present`` flag are recorded so a future
    template/variable-name mismatch surfaces as a metric spike instead of
    silent quality regression (the release-analysis regression this catches
    produced vacuous summaries for weeks before anyone noticed).
    """
    model_string = build_model_string(cfg)
    if not model_string:
        return None
    api_key = cfg.api_key.get_secret_value() if cfg.api_key else None
    agent = get_agent(AnalysisResult, model=model_string, api_key=api_key, base_url=cfg.base_url or None)
    inputs_present = empty_marker is None or empty_marker not in prompt
    if not inputs_present:
        logger.warning(
            "AI analysis prompt is missing expected inputs (empty marker present): kind=%s",
            analysis_kind or "unknown",
        )
    result = await run_extraction(agent, prompt)
    if isinstance(result, AnalysisResult):
        return result
    return AnalysisResult.model_validate(result)


async def analyze_commit_diff(
    *,
    repo_name: str,
    branch: str,
    diff_text: str,
    commit_messages: list[str],
    truncated: TruncatedDiff,
    cfg: AnalysisConfig,
) -> AnalysisResult:
    """Analyze a commit diff (spec repo §8.2, table row 1)."""
    prompt = render_prompt(
        "analysis_prompt.j2",
        repo_name=repo_name,
        branch=branch,
        diff_content=truncated.text,
        commit_messages=commit_messages,
        truncated=truncated.truncated,
        original_diff_length=truncated.original_length,
        analyzed_diff_length=truncated.analyzed_length,
        language=cfg.language,
    )
    try:
        result = await _run_analysis(prompt, cfg, analysis_kind="commit_diff")
    except (ProgressException, Exception) as e:
        logger.warning("commit diff AI analysis failed for %s: %s", repo_name, e)
        report_severe(e)
        record_business_event(
            "progress.repo.ai_failed",
            attributes={"repo": repo_name, "kind": "commit_diff", "reason": type(e).__name__},
        )
        return AnalysisResult(summary=f"**AI analysis unavailable for {repo_name}**", detail="")
    if result is None:
        return AnalysisResult(summary=f"**AI analysis unavailable for {repo_name}**", detail="")
    return result


async def analyze_release(
    *,
    repo_name: str,
    branch: str,
    tag: str,
    name: str | None,
    notes: str,
    published_at: str,
    commit_hash: str | None,
    diff_text: str | None,
    cfg: AnalysisConfig,
) -> AnalysisResult:
    """Analyze a release (spec repo §8.2, table row 2).

    Template variable names mirror ``release_analysis_prompt.j2`` exactly
    (``release_tag`` / ``release_name`` / ``release_published_at`` /
    ``release_notes`` / ``branch``); a previous rename of the prompt left the
    caller passing ``tag`` / ``notes`` / ``published_at``, which Jinja2 treated
    as undefined → the AI saw "No release notes provided." and emitted empty
    summaries even when full notes were available.
    """
    prompt = render_prompt(
        "release_analysis_prompt.j2",
        repo_name=repo_name,
        branch=branch,
        release_tag=tag,
        release_name=name or "",
        release_notes=notes,
        release_published_at=published_at,
        diff_content=diff_text or "",
        language=cfg.language,
    )
    try:
        # ``empty_marker`` is the prompt's own "no notes" fallback string; its
        # presence means ``release_notes`` did not reach the template.
        result = await _run_analysis(prompt, cfg, analysis_kind="release", empty_marker="No release notes provided.")
    except (ProgressException, Exception) as e:
        logger.warning("release AI analysis failed for %s @ %s: %s", repo_name, tag, e)
        report_severe(e)
        record_business_event(
            "progress.repo.ai_failed",
            attributes={"repo": repo_name, "kind": "release", "reason": type(e).__name__},
        )
        return AnalysisResult(summary=f"**AI analysis unavailable for {tag}**", detail="")
    if result is None:
        return AnalysisResult(summary=f"**AI analysis unavailable for {tag}**", detail="")
    return result


async def analyze_readme(
    *,
    repo_name: str,
    description: str | None,
    readme: str,
    cfg: AnalysisConfig,
) -> AnalysisResult:
    """Analyze a discovered repo README (spec repo §8.2, table row 3).

    Per spec repo §8.3 README has no truncation inside the analyzer (caller
    truncates first to MAX_README_LENGTH per §7.3). AI failure does NOT block —
    returns fallback text.
    """
    prompt = render_prompt(
        "readme_analysis_prompt.j2",
        repo_name=repo_name,
        description=description or "",
        readme_content=readme,
        language=cfg.language,
    )
    try:
        result = await _run_analysis(prompt, cfg, analysis_kind="readme")
    except (ProgressException, Exception) as e:
        logger.warning("README AI analysis failed for %s: %s", repo_name, e)
        report_severe(e)
        record_business_event(
            "progress.repo.ai_failed",
            attributes={"repo": repo_name, "kind": "readme", "reason": type(e).__name__},
        )
        return AnalysisResult(
            summary=f"**README analysis unavailable for {repo_name}**",
            detail="",
        )
    if result is None:
        return AnalysisResult(
            summary=f"**README analysis unavailable for {repo_name}**",
            detail="",
        )
    return result


__all__ = [
    "MAX_DIFF_LENGTH",
    "MAX_README_LENGTH",
    "TruncatedDiff",
    "analyze_commit_diff",
    "analyze_readme",
    "analyze_release",
    "truncate_diff",
    "truncate_readme",
]
