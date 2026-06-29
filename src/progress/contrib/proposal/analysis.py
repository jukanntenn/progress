import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from progress.ai import Analyzer
from progress.contrib.repo.analysis import AnalysisResultParser
from progress.telemetry import record_analysis_failure, report_error

from .types import ProposalKind

logger = logging.getLogger(__name__)

_template_dir = Path(__file__).parent.parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)


def run_analysis(
    analyzer: Analyzer,
    template_name: str,
    kind: ProposalKind,
    number: str,
    title: str | None,
    old_raw_status: str | None,
    new_raw_status: str,
    content: str | None = None,
    language: str = "en",
) -> tuple[str, str]:
    try:
        template = _jinja_env.get_template(template_name)
        prompt = template.render(
            kind=kind.value,
            number=number,
            title=title or "",
            old_status=old_raw_status or "",
            new_status=new_raw_status,
            language=language,
        )
        result = analyzer.analyze(
            content=content or "", prompt=prompt, parser=AnalysisResultParser()
        )
        if isinstance(result, tuple):
            logger.debug("Analysis completed: %s #%s", kind.value, number)
            return result
        logger.warning(
            "Analysis returned unexpected type for %s #%s: %s",
            kind.value,
            number,
            type(result).__name__,
        )
        return ("", "")
    except Exception as e:
        logger.warning("Proposal analysis failed for %s #%s: %s", kind.value, number, e)
        provider = getattr(analyzer, "provider", "unknown")
        report_error(
            e,
            kind=kind.value,
            proposal_number=number,
            provider=provider,
            stage="proposal_analysis",
        )
        record_analysis_failure(provider=provider, reason="parse")
        return ("", "")
