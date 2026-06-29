"""Test MarkdownReporter functionality."""

from zoneinfo import ZoneInfo

import pytest

from progress.contrib.repo.reporter import MarkdownReporter
from progress.contrib.repo.repository import RepositoryReport


@pytest.fixture
def reporter():
    """Return a MarkdownReporter instance."""
    return MarkdownReporter()


@pytest.fixture
def mock_report():
    """Return a mock RepositoryReport with HTML in commit messages."""
    report = RepositoryReport(
        repo_name="test/repo",
        repo_slug="test-repo",
        repo_web_url="https://github.com/test/repo",
        branch="main",
        commit_count=2,
        current_commit="abc123",
        previous_commit="def456",
        commit_messages=[
            "<iframe src='https://evil.com'></iframe> Simple commit",
            "Normal commit without HTML",
        ],
        analysis_summary="**Bold** analysis with <strong>HTML</strong>",
        analysis_detail="Detail with <a href='#'>link</a>",
        truncated=False,
        original_diff_length=1000,
        analyzed_diff_length=800,
    )
    return report


def test_fixtures_exist(reporter, mock_report):
    """Test that fixtures are properly configured."""
    assert reporter is not None
    assert mock_report is not None
    assert isinstance(reporter, MarkdownReporter)
    assert isinstance(mock_report, RepositoryReport)


def test_commit_messages_html_escaped(reporter, mock_report):
    """Test that HTML tags in commit messages are escaped."""
    rendered = reporter.generate_repository_report(mock_report)

    # Commit messages should have HTML escaped
    assert "&lt;iframe" in rendered
    assert "&gt;" in rendered
    # The literal iframe tag should NOT appear
    assert "<iframe" not in rendered


def test_analysis_html_not_escaped(reporter, mock_report):
    """Test that HTML in analysis content is NOT escaped."""
    rendered = reporter.generate_repository_report(mock_report)

    # Analysis summary/detail should preserve HTML for markdown rendering
    assert "**Bold**" in rendered
    assert "<strong>" in rendered
    assert "<a href='#'>" in rendered


def test_multiline_commit_with_html_escaped(reporter):
    """Test that HTML in multiline commits is escaped."""
    report = RepositoryReport(
        repo_name="test/repo",
        repo_slug="test-repo",
        repo_web_url="https://github.com/test/repo",
        branch="main",
        commit_count=1,
        current_commit="abc123",
        previous_commit="def456",
        commit_messages=["First line\n<script>alert('xss')</script>\nThird line"],
        analysis_summary="Summary",
        analysis_detail="Detail",
        truncated=False,
        original_diff_length=1000,
        analyzed_diff_length=800,
    )

    rendered = reporter.generate_repository_report(report)

    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered


def test_special_characters_in_commits(reporter):
    """Test that special characters are properly escaped."""
    report = RepositoryReport(
        repo_name="test/repo",
        repo_slug="test-repo",
        repo_web_url="https://github.com/test/repo",
        branch="main",
        commit_count=1,
        current_commit="abc123",
        previous_commit="def456",
        commit_messages=['Commit with &amp; and <tag> and "quotes"'],
        analysis_summary="Summary",
        analysis_detail="Detail",
        truncated=False,
        original_diff_length=1000,
        analyzed_diff_length=800,
    )

    rendered = reporter.generate_repository_report(report)

    assert "&amp;" in rendered  # & should become &amp;amp;
    assert "&lt;tag&gt;" in rendered  # <tag> should be escaped


def test_generate_discovered_repos_report(reporter):
    """Test generating discovered repositories report"""
    timezone = ZoneInfo("UTC")

    repos = [
        {
            "owner_name": "vitejs",
            "repo_name": "vite",
            "repo_url": "https://github.com/vitejs/vite",
            "description": "Next generation frontend tooling",
            "readme_summary": "**Vite** is a build tool",
            "readme_detail": "## Vite\n\nFull details here",
            "discovered_at": "2026-02-11 14:30:00",
        },
        {
            "owner_name": "facebook",
            "repo_name": "react",
            "repo_url": "https://github.com/facebook/react",
            "description": None,
            "readme_summary": None,
            "readme_detail": None,
            "discovered_at": "2026-02-11 12:00:00",
        },
    ]

    result = reporter.generate_discovered_repos_report(repos, timezone)

    assert "# New repositories discovered" in result
    assert "[vitejs/vite](https://github.com/vitejs/vite)" in result
    assert "[facebook/react](https://github.com/facebook/react)" in result
    assert "> Next generation frontend tooling" in result
    assert "🗓2026-02-11 14:30:00" in result
    assert "🗓2026-02-11 12:00:00" in result
    assert "---" in result
    assert result.count("---") == 1  # Only one separator between repos


def test_generate_discovered_repos_report_empty(reporter):
    """Test generating report with no repositories"""
    timezone = ZoneInfo("UTC")

    result = reporter.generate_discovered_repos_report([], timezone)

    assert "# New repositories discovered" in result
    assert "## [" not in result  # No repo sections


def _make_release(tag="v1.0.0"):
    return {
        "title": tag,
        "tag_name": tag,
        "notes": "Release notes for " + tag,
        "ai_summary": "Summary for " + tag,
        "ai_detail": "Detail for " + tag,
    }


def _make_report(repo_name, commit_count=0, releases=None, commit_messages=None):
    return RepositoryReport(
        repo_name=repo_name,
        repo_slug=repo_name.replace("/", "-"),
        repo_web_url="https://github.com/" + repo_name,
        branch="main",
        commit_count=commit_count,
        current_commit="abc123",
        previous_commit=None,
        commit_messages=commit_messages or [],
        analysis_summary="Summary",
        analysis_detail="Detail",
        truncated=False,
        original_diff_length=1000,
        analyzed_diff_length=800,
        releases=releases,
    )


def _has_consecutive_separators(markdown):
    lines = [line.strip() for line in markdown.split("\n")]
    return any(
        lines[i] == "---" and lines[i + 1] == "---" for i in range(len(lines) - 1)
    )


def test_repository_report_releases_only_has_no_separator(reporter):
    report = _make_report("owner/releases-only", releases=[_make_release()])

    rendered = reporter.generate_repository_report(report)

    assert "---" not in rendered


def test_repository_report_releases_with_commits_keeps_single_inner_separator(reporter):
    report = _make_report(
        "owner/both",
        commit_count=1,
        commit_messages=["feat: add thing"],
        releases=[_make_release()],
    )

    rendered = reporter.generate_repository_report(report)

    assert rendered.count("---") == 1


def test_aggregated_report_has_no_consecutive_separators(reporter):
    reports = [
        _make_report("owner/releases-only", releases=[_make_release()]),
        _make_report("owner/commits-only", commit_count=1, commit_messages=["feat: x"]),
        _make_report(
            "owner/both",
            commit_count=1,
            commit_messages=["feat: y"],
            releases=[_make_release()],
        ),
    ]

    result = reporter.generate_aggregated_report(
        reports,
        total_commits=2,
        repo_statuses={r.repo_name: "success" for r in reports},
    )

    assert not _has_consecutive_separators(result)


def test_aggregated_report_separates_each_repo_and_footer(reporter):
    reports = [
        _make_report("owner/a", commit_count=1, commit_messages=["feat: a"]),
        _make_report("owner/b", commit_count=1, commit_messages=["feat: b"]),
    ]

    result = reporter.generate_aggregated_report(
        reports,
        total_commits=2,
        repo_statuses={r.repo_name: "success" for r in reports},
    )

    assert not _has_consecutive_separators(result)
    assert result.count("---") == 2
