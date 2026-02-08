"""Test MarkdownReporter functionality."""

import pytest
from progress.reporter import MarkdownReporter
from progress.repository import RepositoryReport


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
            "Normal commit without HTML"
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
