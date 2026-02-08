# HTML Escape for Commit Messages Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Escape HTML tags in commit messages to prevent rendering issues while preserving HTML rendering for other content.

**Architecture:** Add a Jinja2 filter `_escape_html` to `MarkdownReporter` class and apply it to `commit_messages` in the repository report template. This isolates HTML escaping to only commit message content, leaving AI-generated analysis and other markdown content unaffected.

**Tech Stack:** Python 3.12+, Jinja2 templates, pytest for testing

---

## Task 1: Add test infrastructure for reporter

**Files:**
- Create: `tests/test_reporter.py`

**Step 1: Create test file with basic structure**

```python
"""Test MarkdownReporter functionality."""

import pytest
from progress.reporter import MarkdownReporter
from progress.models import RepositoryReport


@pytest.fixture
def reporter():
    """Return a MarkdownReporter instance."""
    return MarkdownReporter()


@pytest.fixture
def mock_report():
    """Return a mock RepositoryReport with HTML in commit messages."""
    report = RepositoryReport()
    report.repo_name = "test/repo"
    report.repo_web_url = "https://github.com/test/repo"
    report.branch = "main"
    report.commit_count = 2
    report.commit_messages = [
        "<iframe src='https://evil.com'></iframe> Simple commit",
        "Normal commit without HTML"
    ]
    report.analysis_summary = "**Bold** analysis with <strong>HTML</strong>"
    report.analysis_detail = "Detail with <a href='#'>link</a>"
    return report
```

**Step 2: Run test to verify fixture setup**

Run: `uv run pytest tests/test_reporter.py -v`

Expected: PASS (fixtures defined successfully)

**Step 3: Commit**

```bash
git add tests/test_reporter.py
git commit -m "test: add test infrastructure for MarkdownReporter"
```

---

## Task 2: Write failing test for HTML escaping in commit messages

**Files:**
- Modify: `tests/test_reporter.py`

**Step 1: Add test for HTML escaping in commit messages**

```python
def test_commit_messages_html_escaped(reporter, mock_report):
    """Test that HTML tags in commit messages are escaped."""
    rendered = reporter.generate_repository_report(mock_report)

    # Commit messages should have HTML escaped
    assert "&lt;iframe" in rendered
    assert "&gt;" in rendered
    # The literal iframe tag should NOT appear
    assert "<iframe" not in rendered
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reporter.py::test_commit_messages_html_escaped -v`

Expected: FAIL - HTML is currently NOT escaped, so `<iframe` appears in output

**Step 3: Commit**

```bash
git add tests/test_reporter.py
git commit -m "test: add failing test for commit message HTML escaping"
```

---

## Task 3: Write test that other content is NOT escaped

**Files:**
- Modify: `tests/test_reporter.py`

**Step 1: Add test for preserving HTML in analysis content**

```python
def test_analysis_html_not_escaped(reporter, mock_report):
    """Test that HTML in analysis content is NOT escaped."""
    rendered = reporter.generate_repository_report(mock_report)

    # Analysis summary/detail should preserve HTML for markdown rendering
    assert "**Bold**" in rendered
    assert "<strong>" in rendered
    assert "<a href='#'>" in rendered
```

**Step 2: Run test to verify current behavior**

Run: `uv run pytest tests/test_reporter.py::test_analysis_html_not_escaped -v`

Expected: PASS - Current behavior already preserves HTML

**Step 3: Commit**

```bash
git add tests/test_reporter.py
git commit -m "test: add test for preserving HTML in analysis content"
```

---

## Task 4: Implement _escape_html function

**Files:**
- Modify: `src/progress/reporter.py`

**Step 1: Add _escape_html helper function**

Add before the `MarkdownReporter` class:

```python
def _escape_html(text: str) -> str:
    """Escape HTML tags in text.

    Args:
        text: Text to escape

    Returns:
        HTML-escaped text
    """
    from html import escape
    return escape(text)
```

**Step 2: Run tests to verify nothing breaks**

Run: `uv run pytest tests/test_reporter.py -v`

Expected: Tests still fail (Task 2 test), but no new errors

**Step 3: Commit**

```bash
git add src/progress/reporter.py
git commit -m "feat: add _escape_html helper function"
```

---

## Task 5: Register escape_html filter in Jinja2 environment

**Files:**
- Modify: `src/progress/reporter.py:16-30`

**Step 1: Register the filter in __init__**

Modify the `MarkdownReporter.__init__` method to register the filter:

```python
def __init__(self):
    """Initialize reporter with i18n support."""

    template_dir = Path(__file__).parent / "templates"
    self.jinja_env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    self.jinja_env.globals["_"] = _
    self.jinja_env.filters["escape_html"] = _escape_html
```

**Step 2: Run tests to verify filter is registered**

Run: `uv run pytest tests/test_reporter.py -v`

Expected: Task 2 test still FAILS (filter exists but not applied yet), Task 3 test still PASSES

**Step 3: Commit**

```bash
git add src/progress/reporter.py
git commit -m "feat: register escape_html filter in Jinja2 environment"
```

---

## Task 6: Apply escape_html filter to commit_messages in template

**Files:**
- Modify: `src/progress/templates/repository_report.j2:41-50`

**Step 1: Apply filter to commit_messages**

Replace the commit_messages loop section:

```jinja2
{% for msg in report.commit_messages %}
{% if '\n' in msg %}
<details>
<summary>{{ msg.split('\n')[0]|escape_html }}</summary>
{{ msg|escape_html }}
</details>
{% else %}
{{ msg|escape_html }}
{% endif %}
{% endfor %}
```

**Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_reporter.py -v`

Expected: ALL TESTS PASS - HTML is now escaped in commit messages only

**Step 3: Commit**

```bash
git add src/progress/templates/repository_report.j2
git commit -m "feat: apply HTML escaping to commit messages in template"
```

---

## Task 7: Add edge case tests

**Files:**
- Modify: `tests/test_reporter.py`

**Step 1: Add test for multiline commit messages with HTML**

```python
def test_multiline_commit_with_html_escaped(reporter):
    """Test that HTML in multiline commits is escaped."""
    report = RepositoryReport()
    report.repo_name = "test/repo"
    report.repo_web_url = "https://github.com/test/repo"
    report.branch = "main"
    report.commit_count = 1
    report.commit_messages = [
        "First line\n<script>alert('xss')</script>\nThird line"
    ]
    report.analysis_summary = "Summary"
    report.analysis_detail = "Detail"

    rendered = reporter.generate_repository_report(report)

    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered
```

**Step 2: Add test for special characters**

```python
def test_special_characters_in_commits(reporter):
    """Test that special characters are properly escaped."""
    report = RepositoryReport()
    report.repo_name = "test/repo"
    report.repo_web_url = "https://github.com/test/repo"
    report.branch = "main"
    report.commit_count = 1
    report.commit_messages = [
        "Commit with &amp; and <tag> and \"quotes\""
    ]
    report.analysis_summary = "Summary"
    report.analysis_detail = "Detail"

    rendered = reporter.generate_repository_report(report)

    assert "&amp;" in rendered  # & should become &amp;
    assert "&lt;tag&gt;" in rendered  # <tag> should be escaped
```

**Step 3: Run all tests**

Run: `uv run pytest tests/test_reporter.py -v`

Expected: ALL TESTS PASS

**Step 4: Commit**

```bash
git add tests/test_reporter.py
git commit -m "test: add edge case tests for HTML escaping"
```

---

## Task 8: Verify full integration

**Files:**
- No file changes

**Step 1: Run all existing tests to ensure no regression**

Run: `uv run pytest -v`

Expected: All existing tests still pass

**Step 2: Manual verification (optional)**

If you have a repository with HTML in commit messages:
1. Run progress check
2. View the generated report
3. Verify HTML tags in commit messages are displayed as text
4. Verify other markdown content renders correctly

**Step 3: Commit**

```bash
git add docs/plans/2025-02-08-html-escape-implementation.md
git commit -m "docs: add implementation plan for HTML escaping"
```

---

## Summary

This implementation:
- Adds a Jinja2 `escape_html` filter using Python's standard `html.escape()`
- Applies the filter ONLY to `commit_messages` in the repository report template
- Preserves HTML rendering for analysis content and other markdown
- Includes comprehensive tests for the feature
- Follows TDD methodology with failing tests written first
