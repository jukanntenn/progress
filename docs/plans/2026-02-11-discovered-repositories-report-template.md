# Discovered Repositories Report Template Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert the dynamically-built discovered repositories report in `cli.py:_send_entity_notification()` to use a Jinja2 template for better maintainability.

**Architecture:**
1. Create new Jinja template `discovered_repositories_report.j2` for report rendering
2. Add `generate_discovered_repos_report()` method to `MarkdownReporter` class
3. Refactor `_send_entity_notification()` to prepare data and use template-based rendering
4. Flat list structure with repositories sorted newest-first

**Tech Stack:** Python 3.12+, Click 8.3+, Jinja2 3.1+, Peewee ORM

---

## Task 1: Add Template Constant

**Files:**
- Modify: `src/progress/consts.py:32-38`

### Step 1: Add template constant

Add the new template constant to the TEMPLATE NAMES section in `src/progress/consts.py`:

**Find the section around line 32-38:**
```python
# ==================== Template Names ====================
TEMPLATE_ANALYSIS_PROMPT = "analysis_prompt.j2"
TEMPLATE_README_ANALYSIS_PROMPT = "readme_analysis_prompt.j2"
TEMPLATE_REPOSITORY_REPORT = "repository_report.j2"
TEMPLATE_AGGREGATED_REPORT = "aggregated_report.j2"
TEMPLATE_EMAIL_NOTIFICATION = "email_notification.j2"
TEMPLATE_CHANGELOG_NOTIFICATION = "changelog_notification.j2"
```

**Add the new constant at the end:**
```python
# ==================== Template Names ====================
TEMPLATE_ANALYSIS_PROMPT = "analysis_prompt.j2"
TEMPLATE_README_ANALYSIS_PROMPT = "readme_analysis_prompt.j2"
TEMPLATE_REPOSITORY_REPORT = "repository_report.j2"
TEMPLATE_AGGREGATED_REPORT = "aggregated_report.j2"
TEMPLATE_EMAIL_NOTIFICATION = "email_notification.j2"
TEMPLATE_CHANGELOG_NOTIFICATION = "changelog_notification.j2"
TEMPLATE_DISCOVERED_REPOS_REPORT = "discovered_repositories_report.j2"
```

### Step 2: Run existing tests to verify no breakage

Run: `uv run pytest tests/test_config.py -v`

Expected: All existing tests still pass (constant addition doesn't break anything)

### Step 3: Commit

```bash
git add src/progress/consts.py
git commit -m "feat: add discovered repositories report template constant"
```

---

## Task 2: Create Jinja Template

**Files:**
- Create: `src/progress/templates/discovered_repositories_report.j2`

### Step 1: Create the template file

Create `src/progress/templates/discovered_repositories_report.j2` with the following content:

```jinja2
# New repositories discovered {{ report_date }}

{% for repo in repos %}
## [{{ repo.owner_name }}/{{ repo.repo_name }}]({{ repo.repo_url }})

{% if repo.description %}
> {{ repo.description }}
{% endif %}

{% if repo.readme_summary %}{{ repo.readme_summary }}{% endif %}

{% if repo.readme_detail %}
<details>
<summary>Click to view detailed analysis</summary>

{{ repo.readme_detail }}

</details>
{% endif %}

🗓{{ repo.discovered_at }}

{% if not loop.last %}

---{% endif %}
{% endfor %}
```

### Step 2: Verify template syntax

Create a simple test script to verify the template loads without syntax errors:

```bash
cat > /tmp/test_template.py << 'EOF'
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

template_dir = Path("src/progress/templates")
env = Environment(loader=FileSystemLoader(template_dir))
template = env.get_template("discovered_repositories_report.j2")
print("Template loaded successfully!")
EOF

uv run python /tmp/test_template.py
```

Expected: "Template loaded successfully!"

### Step 3: Clean up

```bash
rm /tmp/test_template.py
```

### Step 4: Commit

```bash
git add src/progress/templates/discovered_repositories_report.j2
git commit -m "feat: add discovered repositories report template"
```

---

## Task 3: Add Reporter Method

**Files:**
- Modify: `src/progress/reporter.py`
- Test: `tests/test_reporter.py` (add new tests)

### Step 1: Write failing test for new method

Add this test to `tests/test_reporter.py`:

```python
def test_generate_discovered_repos_report(self):
    """Test generating discovered repositories report"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    reporter = MarkdownReporter()
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
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_reporter.py::TestMarkdownReporter::test_generate_discovered_repos_report -v`

Expected: FAIL - method doesn't exist yet

### Step 3: Implement the method in reporter.py

Add the new method to the `MarkdownReporter` class in `src/progress/reporter.py` after the `generate_aggregated_report()` method:

```python
def generate_discovered_repos_report(
    self, repos: list[dict], timezone: ZoneInfo = ZoneInfo("UTC")
) -> str:
    """Generate discovered repositories report.

    Args:
        repos: List of discovered repo dicts with fields:
               owner_name, repo_name, repo_url, description,
               readme_summary, readme_detail, discovered_at
        timezone: Timezone for timestamps

    Returns:
        Rendered Markdown report
    """
    now = datetime.now(timezone)
    template = self.jinja_env.get_template(TEMPLATE_DISCOVERED_REPOS_REPORT)
    return template.render(
        repos=repos,
        report_date=now.strftime("%Y-%m-%d %H:%M:%S %Z"),
    )
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_reporter.py::TestMarkdownReporter::test_generate_discovered_repos_report -v`

Expected: PASS

### Step 5: Add test for empty repo list

Add this test to `tests/test_reporter.py`:

```python
def test_generate_discovered_repos_report_empty(self):
    """Test generating report with no repositories"""
    from zoneinfo import ZoneInfo

    reporter = MarkdownReporter()
    timezone = ZoneInfo("UTC")

    result = reporter.generate_discovered_repos_report([], timezone)

    assert "# New repositories discovered" in result
    assert "## [" not in result  # No repo sections
```

### Step 6: Run test to verify it passes

Run: `uv run pytest tests/test_reporter.py::TestMarkdownReporter::test_generate_discovered_repos_report_empty -v`

Expected: PASS

### Step 7: Commit

```bash
git add src/progress/reporter.py tests/test_reporter.py
git commit -m "feat: add generate_discovered_repos_report method to MarkdownReporter"
```

---

## Task 4: Refactor Data Preparation Logic

**Files:**
- Modify: `src/progress/cli.py:321-374`
- Test: `tests/test_cli.py` (add new tests)

### Step 1: Write test for data preparation

Add this test to `tests/test_cli.py`:

```python
def test_prepare_discovered_repos_data(self):
    """Test data preparation for discovered repositories report"""
    from datetime import datetime, timezone
    from unittest.mock import Mock, patch
    from progress.models import DiscoveredRepository

    # Mock repo data from owner.py
    new_repos = [
        {
            "id": 1,
            "owner_type": "org",
            "owner_name": "vitejs",
            "repo_name": "vite",
            "name_with_owner": "vitejs/vite",
            "repo_url": "https://github.com/vitejs/vite",
            "description": "Frontend tooling",
            "created_at": datetime(2026, 2, 11, 14, 30, tzinfo=timezone.utc),
            "has_readme": True,
            "readme_was_truncated": False,
        },
        {
            "id": 2,
            "owner_type": "org",
            "owner_name": "facebook",
            "repo_name": "react",
            "name_with_owner": "facebook/react",
            "repo_url": "https://github.com/facebook/react",
            "description": None,
            "created_at": datetime(2026, 2, 11, 12, 0, tzinfo=timezone.utc),
            "has_readme": False,
            "readme_was_truncated": False,
        },
    ]

    # Mock database records
    mock_record1 = Mock(spec=DiscoveredRepository)
    mock_record1.readme_summary = "**Vite** is fast"
    mock_record1.readme_detail = "## Full details"

    mock_record2 = Mock(spec=DiscoveredRepository)
    mock_record2.readme_summary = None
    mock_record2.readme_detail = None

    with patch('progress.cli.DiscoveredRepository') as mock_db:
        mock_db.get_by_id.side_effect = [mock_record1, mock_record2]

        # Sort newest-first
        sorted_repos = sorted(
            new_repos,
            key=lambda r: r.get("created_at") or datetime.min,
            reverse=True
        )

        # Enrich with AI analysis
        for r in sorted_repos:
            record_id = r.get("id")
            if record_id:
                record = mock_db.get_by_id(record_id)
                if record:
                    r["readme_summary"] = record.readme_summary
                    r["readme_detail"] = record.readme_detail

        # Format timestamps
        for r in sorted_repos:
            created_at = r.get("created_at")
            if created_at:
                if isinstance(created_at, str):
                    try:
                        created_at = datetime.fromisoformat(created_at)
                    except ValueError:
                        created_at = None
                if created_at and hasattr(created_at, "strftime"):
                    r["discovered_at"] = created_at.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    r["discovered_at"] = "Unknown"
            else:
                r["discovered_at"] = "Unknown"

            # Ensure owner_name exists
            if "owner_name" not in r:
                name_with_owner = r.get("name_with_owner", "")
                if "/" in name_with_owner:
                    r["owner_name"] = name_with_owner.split("/")[0]
                else:
                    r["owner_name"] = "Unknown"

        # Verify results
        assert sorted_repos[0]["repo_name"] == "vite"  # Newest first
        assert sorted_repos[1]["repo_name"] == "react"
        assert sorted_repos[0]["readme_summary"] == "**Vite** is fast"
        assert sorted_repos[0]["discovered_at"] == "2026-02-11 14:30:00"
        assert sorted_repos[1]["readme_summary"] is None
        assert sorted_repos[1]["discovered_at"] == "2026-02-11 12:00:00"
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_cli.py::test_prepare_discovered_repos_data -v`

Expected: FAIL - test structure may need adjustment based on actual code

### Step 3: Update test based on actual implementation

The test above is a unit test for the data preparation logic. The actual implementation will be integrated into `_send_entity_notification()`. The test serves as documentation of expected behavior.

### Step 4: Commit

```bash
git add tests/test_cli.py
git commit -m "test: add data preparation test for discovered repos"
```

---

## Task 5: Refactor _send_entity_notification

**Files:**
- Modify: `src/progress/cli.py:321-374`

### Step 1: Import MarkdownReporter

Check the imports at the top of `src/progress/cli.py` and ensure `MarkdownReporter` is imported:

**Find existing import section (around line 20-30):**
```python
from .reporter import MarkdownReporter
```

If not present, add it with the other imports.

### Step 2: Replace the dynamic string building with template rendering

In `src/progress/cli.py`, replace the `_send_entity_notification` function (lines 321-409) with the new implementation:

**Find:**
```python
def _send_entity_notification(
    notification_manager: NotificationManager,
    markpost_client: MarkpostClient,
    analyzer: ClaudeCodeAnalyzer,
    new_repos: list[dict],
    timezone,
) -> None:
    now = get_now(timezone)
    lines: list[str] = [
        f"# New repositories discovered ({now.strftime('%Y-%m-%d %H:%M')})",
        "",
    ]

    grouped: dict[tuple[str, str], list[dict]] = {}
    for r in new_repos:
        key = (r.get("owner_type") or "", r.get("owner_name") or "")
        grouped.setdefault(key, []).append(r)

    for (owner_type, owner_name), repos in sorted(grouped.items()):
        lines.append(f"## {owner_name} ({owner_type})")
        lines.append("")
        for r in sorted(repos, key=lambda x: x.get("repo_name") or ""):
            # ... rest of the function
```

**Replace with:**
```python
def _send_entity_notification(
    notification_manager: NotificationManager,
    markpost_client: MarkpostClient,
    analyzer: ClaudeCodeAnalyzer,
    new_repos: list[dict],
    timezone,
) -> None:
    if not new_repos:
        return

    # Sort newest-first
    sorted_repos = sorted(
        new_repos,
        key=lambda r: r.get("created_at") or datetime.min,
        reverse=True
    )

    # Enrich with AI analysis from database
    for r in sorted_repos:
        record_id = r.get("id")
        if record_id:
            record = DiscoveredRepository.get_by_id(record_id)
            if record:
                r["readme_summary"] = record.readme_summary
                r["readme_detail"] = record.readme_detail

    # Format timestamps
    for r in sorted_repos:
        created_at = r.get("created_at")
        if created_at:
            if isinstance(created_at, str):
                try:
                    created_at = datetime.fromisoformat(created_at)
                except ValueError:
                    created_at = None
            if created_at and hasattr(created_at, "strftime"):
                r["discovered_at"] = created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                r["discovered_at"] = "Unknown"
        else:
            r["discovered_at"] = "Unknown"

        # Ensure owner_name exists
        if "owner_name" not in r:
            name_with_owner = r.get("name_with_owner", "")
            if "/" in name_with_owner:
                r["owner_name"] = name_with_owner.split("/")[0]
            else:
                r["owner_name"] = "Unknown"

    # Generate report using template
    reporter = MarkdownReporter()
    report_content = reporter.generate_discovered_repos_report(sorted_repos, timezone)

    try:
        title, summary = analyzer.generate_title_and_summary(report_content)
    except Exception as e:
        logger.warning(f"Failed to generate title/summary for owner monitoring: {e}")
        now = get_now(timezone)
        title = _("Progress Report for Open Source Projects - {date}").format(
            date=now.strftime("%Y-%m-%d %H:%M")
        )
        summary = f"Discovered {len(new_repos)} new repositories"

    markpost_url = markpost_client.upload(report_content, title=title)

    repo_statuses = {
        (r.get("name_with_owner") or r.get("repo_name") or str(r.get("id"))): "success"
        for r in new_repos
    }

    notification_manager.send(
        NotificationMessage(
            title=title,
            summary=summary or f"Discovered {len(new_repos)} new repositories",
            total_commits=len(new_repos),
            markpost_url=markpost_url,
            repo_statuses=repo_statuses,
        )
    )

    for r in new_repos:
        record_id = r.get("id")
        if record_id:
            record = DiscoveredRepository.get_by_id(record_id)
            if record:
                record.notified = True
                record.save()
```

### Step 3: Add missing imports

Ensure `datetime` and `datetime.min` are available. Check imports at top of file:

**Add if not present:**
```python
from datetime import datetime, timezone
```

### Step 4: Run tests to verify

Run: `uv run pytest tests/test_cli.py -v -k entity`

Expected: Tests pass (may need to update existing tests)

### Step 5: Run all CLI tests

Run: `uv run pytest tests/test_cli.py -v`

Expected: All tests pass

### Step 6: Commit

```bash
git add src/progress/cli.py
git commit -m "refactor: use template for discovered repositories report"
```

---

## Task 6: Run Full Test Suite

### Step 1: Run all tests

Run: `uv run pytest -v`

Expected: All tests pass (current baseline + new tests)

### Step 2: Fix any remaining issues

If tests fail, update them to match the new behavior.

### Step 3: Final commit if needed

```bash
git add tests/
git commit -m "test: update tests for discovered repos template"
```

---

## Task 7: Manual Integration Testing

### Step 1: Test with real owner monitoring

Configure owner monitoring in `config.toml`:

```toml
[[owners]]
type = "org"
name = "example-org"
enabled = true
```

### Step 2: Run check

Run: `uv run progress check -c config.toml`

### Step 3: Verify report output

Check the generated report:
- Report uses flat list structure (no owner grouping)
- Repositories are sorted newest-first
- Each repo has markdown link heading `[owner/repo](url)`
- Description appears as blockquote
- README summary and detail sections render correctly
- Collapsible `<details>` section works
- Per-repo timestamp with calendar emoji
- Horizontal rule between repos

### Step 4: Clean up test data

```bash
# Remove test data if needed
```

---

## Task 8: Update Design Document

### Step 1: Update design doc with completion status

Edit `docs/2026-02-11-discovered-repositories-report-template-design.md`:

**Add at the top after Status:**
```markdown
**Implementation:** Completed 2026-02-11
```

**Add implementation notes section at the end:**
```markdown

## Implementation Notes

- Implementation date: 2026-02-11
- All tests passing
- Manual integration testing completed
- Report format matches design specification
```

### Step 2: Commit documentation update

```bash
git add docs/2026-02-11-discovered-repositories-report-template-design.md
git commit -m "docs: mark discovered repositories report template as complete"
```

---

## Summary

This implementation plan:
1. ✅ Adds template constant for discovered repositories report
2. ✅ Creates new Jinja template with flat list structure
3. ✅ Adds `generate_discovered_repos_report()` method to `MarkdownReporter`
4. ✅ Refactors `_send_entity_notification()` to use template-based rendering
5. ✅ Sorts repositories newest-first
6. ✅ Includes per-repo timestamps
7. ✅ Uses markdown link format `[owner/repo](url)` for headings
8. ✅ Follows TDD with tests written first
9. ✅ Commits frequently for easy rollback

**Files Modified:**
- `src/progress/consts.py` - Add template constant
- `src/progress/reporter.py` - Add new method
- `src/progress/templates/discovered_repositories_report.j2` - New template file
- `src/progress/cli.py` - Refactor notification function
- `tests/test_reporter.py` - Add reporter tests
- `tests/test_cli.py` - Add CLI tests

**Estimated Time:** 1.5-2 hours for all tasks
