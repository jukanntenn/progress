from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from progress.contrib.repo.analysis import (
    AnalysisResultParser,
    _extract_json,
    analyze_diff,
    analyze_readme,
    analyze_releases,
)
from progress.errors import AnalysisException


class TestExtractJson:
    def test_extracts_json_from_plain_string(self):
        output = '{"summary": "s", "detail": "d"}'
        assert _extract_json(output) == output

    def test_extracts_json_from_surrounding_text(self):
        output = 'Here is the result:\n{"summary": "s", "detail": "d"}\nDone.'
        assert _extract_json(output) == '{"summary": "s", "detail": "d"}'

    def test_raises_when_no_json_found(self):
        with pytest.raises(AnalysisException, match="Could not extract JSON"):
            _extract_json("no json here")

    def test_extracts_multiline_json(self):
        output = 'prefix\n{\n  "summary": "s",\n  "detail": "d"\n}\nsuffix'
        result = _extract_json(output)
        assert '"summary"' in result
        assert '"detail"' in result


class TestAnalysisResultParser:
    def test_parses_valid_json(self):
        parser = AnalysisResultParser()
        output = '{"summary": "short", "detail": "long text"}'
        summary, detail = parser.parse(output)
        assert summary == "short"
        assert detail == "long text"

    def test_parses_json_with_surrounding_text(self):
        parser = AnalysisResultParser()
        output = 'Analysis complete:\n{"summary": "s", "detail": "d"}\nEnd.'
        summary, detail = parser.parse(output)
        assert summary == "s"
        assert detail == "d"

    def test_raises_on_missing_summary(self):
        parser = AnalysisResultParser()
        with pytest.raises(AnalysisException, match="missing 'summary'"):
            parser.parse('{"detail": "d"}')

    def test_raises_on_missing_detail(self):
        parser = AnalysisResultParser()
        with pytest.raises(AnalysisException, match="missing 'summary'"):
            parser.parse('{"summary": "s"}')

    def test_raises_on_empty_summary(self):
        parser = AnalysisResultParser()
        with pytest.raises(AnalysisException, match="missing 'summary'"):
            parser.parse('{"summary": "", "detail": "d"}')

    def test_raises_on_empty_detail(self):
        parser = AnalysisResultParser()
        with pytest.raises(AnalysisException, match="missing 'summary'"):
            parser.parse('{"summary": "s", "detail": ""}')

    def test_raises_on_no_json(self):
        parser = AnalysisResultParser()
        with pytest.raises(AnalysisException, match="Could not extract JSON"):
            parser.parse("no json here")

    def test_raises_on_invalid_json(self):
        parser = AnalysisResultParser()
        with pytest.raises(json.JSONDecodeError):
            parser.parse("{invalid json}")


def _make_analyzer(return_value=None, side_effect=None):
    analyzer = MagicMock()
    if side_effect:
        analyzer.analyze.side_effect = side_effect
    else:
        analyzer.analyze.return_value = return_value or ("summary", "detail")
    return analyzer


class TestAnalyzeDiff:
    def test_calls_analyzer_with_parser(self):
        analyzer = _make_analyzer()
        analyze_diff(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            diff="some diff",
            commit_messages=["msg1"],
            max_diff_length=10000,
            language="en",
        )
        analyzer.analyze.assert_called_once()
        call_kwargs = analyzer.analyze.call_args
        assert call_kwargs.kwargs["parser"] is not None
        assert isinstance(call_kwargs.kwargs["parser"], AnalysisResultParser)

    def test_truncates_long_diff(self):
        analyzer = _make_analyzer(return_value=("s", "d"))
        summary, detail, truncated, orig_len, analyzed_len = analyze_diff(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            diff="a" * 100,
            commit_messages=["msg"],
            max_diff_length=50,
            language="en",
        )
        assert truncated is True
        assert orig_len == 100
        assert analyzed_len == 50

    def test_no_truncation_when_short(self):
        analyzer = _make_analyzer(return_value=("s", "d"))
        _, _, truncated, orig_len, analyzed_len = analyze_diff(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            diff="short diff",
            commit_messages=["msg"],
            max_diff_length=10000,
            language="en",
        )
        assert truncated is False
        assert orig_len == analyzed_len

    def test_fallback_on_analysis_failure(self):
        analyzer = _make_analyzer(side_effect=Exception("timeout"))
        summary, detail, _, _, _ = analyze_diff(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            diff="diff",
            commit_messages=["msg"],
            max_diff_length=10000,
            language="en",
        )
        assert summary != ""
        assert detail != ""

    def test_failure_reports_error_and_parse_metric(self, monkeypatch):
        analyzer = _make_analyzer(side_effect=ValueError("bad json"))
        reported = []
        counted = []
        monkeypatch.setattr(
            "progress.contrib.repo.analysis.report_error",
            lambda exc, **tags: reported.append((exc, tags)),
        )
        monkeypatch.setattr(
            "progress.contrib.repo.analysis.record_analysis_failure",
            lambda **kw: counted.append(kw),
        )

        analyze_diff(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            diff="diff",
            commit_messages=["msg"],
            max_diff_length=10000,
            language="en",
        )

        assert len(reported) == 1
        assert isinstance(reported[0][0], ValueError)
        assert reported[0][1]["stage"] == "diff_analysis"
        assert reported[0][1]["repo"] == "owner/repo"
        assert counted == [{"provider": analyzer.provider, "reason": "parse"}]


def _make_release_data():
    return {
        "releases": [{"tag": "v1.0"}],
        "latest_release": {
            "tag": "v1.0",
            "name": "Release 1.0",
            "published_at": "2025-01-01",
            "notes": "Initial release",
        },
    }


class TestAnalyzeReleases:
    def test_calls_analyzer(self):
        analyzer = _make_analyzer(return_value=("s", "d"))
        result = analyze_releases(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            release_data=_make_release_data(),
            language="en",
        )
        assert result == ("s", "d")
        analyzer.analyze.assert_called_once()

    def test_uses_parser(self):
        analyzer = _make_analyzer()
        analyze_releases(
            analyzer,
            repo_name="owner/repo",
            branch="main",
            release_data=_make_release_data(),
            language="en",
        )
        call_kwargs = analyzer.analyze.call_args
        assert isinstance(call_kwargs.kwargs["parser"], AnalysisResultParser)


class TestAnalyzeReadme:
    def test_calls_analyzer(self):
        analyzer = _make_analyzer(return_value=("s", "d"))
        result = analyze_readme(
            analyzer,
            repo_name="owner/repo",
            description="A project",
            readme_content="# README",
            language="en",
        )
        assert result == ("s", "d")
        analyzer.analyze.assert_called_once()

    def test_uses_parser(self):
        analyzer = _make_analyzer()
        analyze_readme(
            analyzer,
            repo_name="owner/repo",
            description=None,
            readme_content="content",
            language="en",
        )
        call_kwargs = analyzer.analyze.call_args
        assert isinstance(call_kwargs.kwargs["parser"], AnalysisResultParser)
