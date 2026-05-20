import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from progress.ai import Analyzer
from progress.contrib.repo.analysis import AnalysisResultParser
from progress.i18n import gettext as _

logger = logging.getLogger(__name__)

_template_dir = Path(__file__).parent.parent.parent / "templates"
_jinja_env = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(),
    trim_blocks=True,
    lstrip_blocks=True,
)

_TEMPLATE_MAP = {
    "accepted": "proposal_accepted_prompt.j2",
    "rejected": "proposal_rejected_prompt.j2",
    "withdrawn": "proposal_withdrawn_prompt.j2",
    "status_changed": "proposal_status_change_prompt.j2",
}


def analyze_proposal(
    analyzer: Analyzer,
    *,
    proposal_type: str,
    event_type: str,
    proposal_number: int,
    title: str,
    old_status: str | None = None,
    new_status: str | None = None,
    proposal_text: str | None = None,
    diff_text: str | None = None,
    language: str = "en",
) -> tuple[str, str]:
    if event_type == "created":
        return _analyze_new(
            analyzer,
            proposal_type,
            proposal_number,
            title,
            proposal_text or "",
            language,
        )
    if event_type in _TEMPLATE_MAP:
        return _analyze_status_change(
            analyzer,
            proposal_type,
            proposal_number,
            title,
            event_type,
            old_status or "",
            new_status or "",
            proposal_text or "",
            language,
        )
    if event_type == "content_modified":
        return _analyze_content_modification(
            analyzer,
            proposal_type,
            proposal_number,
            title,
            diff_text or "",
            language,
        )
    return ("", "")


def _analyze_new(
    analyzer, proposal_type, proposal_number, title, proposal_text, language
):
    template = _jinja_env.get_template("proposal_new_prompt.j2")
    prompt = template.render(
        proposal_type=proposal_type,
        proposal_number=proposal_number,
        title=title,
        language=language,
    )
    try:
        return analyzer.analyze(
            content=proposal_text, prompt=prompt, parser=AnalysisResultParser()
        )
    except Exception as e:
        logger.warning("Proposal analysis failed: %s", e)
        return (
            _(f"New proposal: {proposal_type} #{proposal_number}"),
            _(f"Analysis unavailable for {proposal_type} #{proposal_number}: {title}"),
        )


def _analyze_status_change(
    analyzer,
    proposal_type,
    proposal_number,
    title,
    event_type,
    old_status,
    new_status,
    proposal_text,
    language,
):
    template_name = _TEMPLATE_MAP[event_type]
    template = _jinja_env.get_template(template_name)
    prompt = template.render(
        proposal_type=proposal_type,
        proposal_number=proposal_number,
        title=title,
        old_status=old_status,
        new_status=new_status,
        language=language,
    )
    try:
        return analyzer.analyze(
            content=proposal_text, prompt=prompt, parser=AnalysisResultParser()
        )
    except Exception as e:
        logger.warning("Proposal analysis failed: %s", e)
        return (
            _(f"Status changed: {proposal_type} #{proposal_number}"),
            _(
                f"Analysis unavailable for {proposal_type} #{proposal_number}: "
                f"{title} ({old_status} -> {new_status})"
            ),
        )


def _analyze_content_modification(
    analyzer,
    proposal_type,
    proposal_number,
    title,
    diff_text,
    language,
):
    template = _jinja_env.get_template("proposal_content_modified_prompt.j2")
    prompt = template.render(
        proposal_type=proposal_type,
        proposal_number=proposal_number,
        title=title,
        language=language,
    )
    try:
        return analyzer.analyze(
            content=diff_text, prompt=prompt, parser=AnalysisResultParser()
        )
    except Exception as e:
        logger.warning("Proposal analysis failed: %s", e)
        return (
            _(f"Content modified: {proposal_type} #{proposal_number}"),
            _(f"Analysis unavailable for {proposal_type} #{proposal_number}: {title}"),
        )
