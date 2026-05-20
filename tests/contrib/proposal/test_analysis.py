from __future__ import annotations

from unittest.mock import MagicMock

from progress.contrib.proposal.analysis import analyze_proposal
from progress.contrib.repo.analysis import AnalysisResultParser


def _make_analyzer(return_value=None, side_effect=None):
    analyzer = MagicMock()
    if side_effect:
        analyzer.analyze.side_effect = side_effect
    else:
        analyzer.analyze.return_value = return_value or ("summary", "detail")
    return analyzer


class TestAnalyzeProposal:
    def test_analyze_new_proposal(self):
        analyzer = _make_analyzer(return_value=("New EIP", "Details"))
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="created",
            proposal_number=123,
            title="Test Proposal",
            proposal_text="proposal content",
            language="en",
        )
        assert result == ("New EIP", "Details")
        analyzer.analyze.assert_called_once()
        call_kwargs = analyzer.analyze.call_args.kwargs
        assert isinstance(call_kwargs["parser"], AnalysisResultParser)
        assert call_kwargs["content"] == "proposal content"

    def test_analyze_status_change_accepted(self):
        analyzer = _make_analyzer(return_value=("Accepted", "Details"))
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="accepted",
            proposal_number=123,
            title="Test Proposal",
            old_status="draft",
            new_status="accepted",
            proposal_text="text",
            language="en",
        )
        assert result == ("Accepted", "Details")
        analyzer.analyze.assert_called_once()

    def test_analyze_status_change_rejected(self):
        analyzer = _make_analyzer(return_value=("Rejected", "Details"))
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="rejected",
            proposal_number=123,
            title="Test Proposal",
            old_status="draft",
            new_status="rejected",
            language="en",
        )
        assert result == ("Rejected", "Details")
        analyzer.analyze.assert_called_once()

    def test_analyze_status_change_withdrawn(self):
        analyzer = _make_analyzer(return_value=("Withdrawn", "Details"))
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="withdrawn",
            proposal_number=123,
            title="Test Proposal",
            language="en",
        )
        assert result == ("Withdrawn", "Details")
        analyzer.analyze.assert_called_once()

    def test_analyze_content_modified(self):
        analyzer = _make_analyzer(return_value=("Modified", "Details"))
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="content_modified",
            proposal_number=123,
            title="Test Proposal",
            diff_text="some diff",
            language="en",
        )
        assert result == ("Modified", "Details")
        call_kwargs = analyzer.analyze.call_args.kwargs
        assert call_kwargs["content"] == "some diff"

    def test_unknown_event_type_returns_empty(self):
        analyzer = _make_analyzer()
        result = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="unknown_event",
            proposal_number=123,
            title="Test",
            language="en",
        )
        assert result == ("", "")
        analyzer.analyze.assert_not_called()

    def test_fallback_on_analysis_failure_new(self):
        analyzer = _make_analyzer(side_effect=Exception("timeout"))
        summary, detail = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="created",
            proposal_number=42,
            title="My Proposal",
            language="en",
        )
        assert "EIP" in summary
        assert "42" in summary
        assert detail != ""

    def test_fallback_on_analysis_failure_status_change(self):
        analyzer = _make_analyzer(side_effect=Exception("timeout"))
        summary, detail = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="accepted",
            proposal_number=42,
            title="My Proposal",
            old_status="draft",
            new_status="accepted",
            language="en",
        )
        assert "EIP" in summary
        assert "42" in summary
        assert detail != ""

    def test_fallback_on_analysis_failure_content_modified(self):
        analyzer = _make_analyzer(side_effect=Exception("timeout"))
        summary, detail = analyze_proposal(
            analyzer,
            proposal_type="EIP",
            event_type="content_modified",
            proposal_number=42,
            title="My Proposal",
            language="en",
        )
        assert "EIP" in summary
        assert "42" in summary
        assert detail != ""
