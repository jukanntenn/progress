# Discovered Repositories Report Template Design

**Date:** 2026-02-11
**Status:** Approved

## Overview

Convert the dynamically-built discovered repositories report in `cli.py:_send_entity_notification()` to use a Jinja2 template. The current implementation builds markdown strings via concatenation, which is hard to maintain and modify.

## Goals

1. Create reusable Jinja2 template for discovered repositories report
2. Use flat list structure (no owner grouping)
3. Sort repositories newest-first by discovery date
4. Include per-repo timestamps with calendar emoji
5. Use markdown link format `[owner/repo](repo_url)` for headings

## Template Structure

**New file:** `src/progress/templates/discovered_repositories_report.j2`

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

**Template Features:**
- Level-1 heading with report timestamp
- Level-2 heading with markdown link `[owner/repo](url)`
- Description as blockquote `> description` (if present)
- README summary section (if available)
- README detail in collapsible `<details>` section (if available)
- Per-repo timestamp with calendar emoji
- Horizontal rule between repos (not after last one)

## Data Structure

**Fields expected by template per repository:**

| Field | Type | Description | Example |
|-------|------|-------------|---------|
| `owner_name` | `str` | Organization or username | `"vitejs"` |
| `repo_name` | `str` | Repository name | `"vite"` |
| `repo_url` | `str` | Full GitHub URL | `"https://github.com/vitejs/vite"` |
| `description` | `str \| None` | Repository description | `"Next generation frontend tooling"` |
| `readme_summary` | `str \| None` | AI-generated README summary | `"Vite is a build tool..."` |
| `readme_detail` | `str \| None` | AI-generated detailed analysis | Full markdown analysis |
| `discovered_at` | `str` | Formatted timestamp | `"2026-02-11 14:30:00"` |

## Code Changes

### 1. `src/progress/consts.py`

Add template constant (around line 38):

```python
TEMPLATE_DISCOVERED_REPOS_REPORT = "discovered_repositories_report.j2"
```

### 2. `src/progress/reporter.py`

Add new method to `MarkdownReporter` class after `generate_aggregated_report()`:

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

### 3. `src/progress/cli.py` - Refactor `_send_entity_notification()`

Replace lines 329-374 (dynamic string building) with:

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

## Data Flow

```
owner.py:_check_owner()
    └─> Returns list[dict] from _process_new_repo()
            with keys: id, owner_type, owner_name, repo_name,
                      name_with_owner, repo_url, description,
                      created_at, has_readme, readme_content

        ↓

cli.py:_send_entity_notification()
    ├─> Sort by created_at descending (newest first)
    ├─> Fetch readme_summary, readme_detail from DiscoveredRepository
    ├─> Format discovered_at timestamp
    ├─> Ensure owner_name field exists
    └─> Call reporter.generate_discovered_repos_report()

        ↓

reporter.py:MarkdownReporter
    └─> Renders discovered_repositories_report.j2
    └─> Returns complete markdown string
```

## Error Handling & Edge Cases

| Case | Handling |
|------|----------|
| Empty repository list | Skip notification entirely (existing behavior) |
| Missing description | Template conditional skips rendering |
| No README file | `readme_summary` and `readme_detail` are `None`, template skips |
| AI analysis not run | Report shows repo info without AI analysis sections |
| Missing created_at | Use `"Unknown"` for `discovered_at` timestamp |
| Invalid datetime format | Catch `ValueError`, fall back to `"Unknown"` |
| Missing owner_name | Extract from `name_with_owner` or use `"Unknown"` |

## Testing Strategy

### Unit Tests to Add (`tests/test_reporter.py`)

- Test `generate_discovered_repos_report()` with empty list
- Test with single repo (all fields present)
- Test with multiple repos (verify sorting)
- Test with missing optional fields
- Test timestamp formatting with different timezones

### Unit Tests to Add (`tests/test_cli.py`)

- Test sorting by `created_at` descending
- Test enrichment with database fields
- Test timestamp formatting for valid/invalid datetime
- Test `owner_name` extraction from `name_with_owner`

### Manual Testing

- Run `progress check` with configured owners
- Verify report format matches expected output
- Check markdown rendering in notification destination
- Verify collapsible `<details>` sections work

## File Changes Summary

| File | Change Type | Lines |
|------|-------------|-------|
| `src/progress/consts.py` | Add constant | +1 |
| `src/progress/reporter.py` | Add method | +15-20 |
| `src/progress/templates/discovered_repositories_report.j2` | New file | +30 |
| `src/progress/cli.py` | Refactor function | -45, +30-35 (net ~-15) |
| `tests/test_reporter.py` | Add tests | +50-80 |
| `tests/test_cli.py` | Add tests | +40-60 |

**Total:** Net increase of ~100-150 lines (including tests)

## Breaking Changes

None. Report format changes, but:
- Notification flow remains the same
- `owner.py` and database model unchanged
- `DiscoveredRepository` fields unchanged

## Performance Considerations

- Additional database query per repo to fetch `readme_summary`/`readme_detail`
- For typical volumes (1-10 repos per check), individual queries acceptable
- Can optimize with bulk query if needed:
  ```python
  records = DiscoveredRepository.select().where(
      DiscoveredRepository.id.in_([r["id"] for r in sorted_repos if r.get("id")])
  )
  record_map = {r.id: r for r in records}
  ```

## Design Principles

- **YAGNI:** Simple flat list, no complex owner grouping
- **Consistency:** Uses existing `MarkdownReporter` pattern
- **Maintainability:** Template is easier to modify than string concatenation
- **Testability:** Clear separation of data prep and rendering
