"""Test MarkdownReporter functionality."""

import pytest
from zoneinfo import ZoneInfo
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
