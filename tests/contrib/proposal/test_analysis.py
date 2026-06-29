from __future__ import annotations

from unittest.mock import Mock

from progress.contrib.proposal.analysis import run_analysis
from progress.contrib.proposal.types import ProposalKind


def _mock_analyzer(side_effect=None):
    analyzer = Mock()
    analyzer.provider = "claude_code"
    if side_effect:
        analyzer.analyze.side_effect = side_effect
    else:
        analyzer.analyze.return_value = ("summary", "detail")
    return analyzer


def test_run_analysis_returns_result_on_success():
    analyzer = _mock_analyzer()

    summary, detail = run_analysis(
        analyzer,
        "proposal_new_prompt.j2",
        ProposalKind.EIP,
        "1",
        "Title",
        None,
        "Draft",
        content="body",
    )

    assert (summary, detail) == ("summary", "detail")


def test_run_analysis_reports_error_and_parse_metric_on_failure(monkeypatch):
    analyzer = _mock_analyzer(side_effect=ValueError("bad json"))
    reported = []
    counted = []
    monkeypatch.setattr(
        "progress.contrib.proposal.analysis.report_error",
        lambda exc, **tags: reported.append((exc, tags)),
    )
    monkeypatch.setattr(
        "progress.contrib.proposal.analysis.record_analysis_failure",
        lambda **kw: counted.append(kw),
    )

    summary, detail = run_analysis(
        analyzer,
        "proposal_new_prompt.j2",
        ProposalKind.EIP,
        "1",
        "Title",
        None,
        "Draft",
        content="body",
    )

    assert (summary, detail) == ("", "")
    assert len(reported) == 1
    assert isinstance(reported[0][0], ValueError)
    assert reported[0][1]["kind"] == "eip"
    assert reported[0][1]["proposal_number"] == "1"
    assert reported[0][1]["stage"] == "proposal_analysis"
    assert counted == [{"provider": "claude_code", "reason": "parse"}]
