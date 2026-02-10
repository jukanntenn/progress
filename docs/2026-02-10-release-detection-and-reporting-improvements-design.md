# Release Detection and Reporting Improvements Design

**Date:** 2026-02-10
**Status:** Approved

## Overview

Improve release detection and reporting by:
1. Adding `--tags` flag to git clone operations
2. Simplifying release detection by eliminating "intermediate releases" concept
3. Generating individual AI analysis for each new release
4. Standardizing report format with consistent release sections

## Architecture & Core Changes

### Tag Fetching

Modify `gh repo clone` command in `repo.py` (~lines 512-522):

**Current:**
```bash
gh repo clone {repo} {dir} --single-branch --branch {branch}
```

**New:**
```bash
gh repo clone {repo} {dir} --single-branch --branch {branch} -- --tags
```

The double-dash (`--`) passes subsequent flags to git. Update any `git fetch` operations similarly.

**Benefits:**
- Tags available locally for fallback if GitHub API fails
- Potential for offline analysis
- Tag verification against API data
- Foundation for future local-tag-based features

### Release Detection Logic

Continue using GitHub API via `GitHubClient.list_releases()` as primary source. Local tags provide backup and verification.

**Key Changes:**
- Remove `intermediate_releases` logic and variable
- Simplify `check_releases()` to return flat list of new releases
- Each release object: tag name, title, body, publish date, commit hash
- Remove conditional logic treating first release differently

### Report Template Changes

Restructure `repository_report.j2` to support multiple releases with individual AI analysis. Replace "single release + intermediate releases list" with loop rendering each release identically.

## Components & Data Flow

### Modified Components

**1. `repo.py` (Git operations)**
- Update `clone_repo()` to add `-- --tags` to gh clone command
- Update `fetch()` method to include `--tags` if it exists

**2. `repo.py` (Release checking, ~lines 323-349)**
- Remove `intermediate_releases` logic
- Simplify `check_releases()` to return flat list of new releases
- Remove conditional logic for first vs subsequent releases

**3. `github_client.py`**
- No changes needed

**4. `reporter.py`**
- Modify release analysis to call AI for EACH release individually
- Current: one batch API call
- New: N calls (one per release)
- Each call uses `release_analysis_prompt.j2` for single release
- Aggregate results into list of analyzed releases (release info + AI summary + AI detail)

**5. `repository_report.j2`**
- Replace current release section with Jinja2 loop over analyzed releases
- Loop renders each release using standardized structure
- Order list newest-first before passing to template

### Data Flow

```
GitHub API -> list of new releases -> loop through each release
    |
    v
For each release: fetch commit diff -> call Claude AI -> get {summary, detail}
    |
    v
Aggregate all analyzed releases -> pass to template -> render report
```

### Release Object Structure

Each release in the template loop will have:
- `title`: Release title from GitHub
- `tag_name`: Git tag (e.g., "v1.2.3")
- `body`: Full release notes (markdown)
- `publish_date`: Formatted date string
- `ai_summary`: AI-generated brief overview
- `ai_detail`: AI-generated in-depth analysis

## Error Handling & Edge Cases

### AI Analysis Failures

When Claude API fails for a specific release:
- Catch exception at individual release level
- Mark release as `analysis_failed=True`
- Continue processing remaining releases
- In template: show release notes but display *"AI analysis unavailable - [error reason]"*
- Log failure for debugging

### Empty Release List

If no new releases since last check:
- Skip entire release section (no "**0 releases**" header)
- Behavior unchanged from current system

### No Release Notes

If release has empty body:
- Render collapsible section with *"No release notes provided"*
- Still show AI summary (based on commit diff) and detail
- Maintain consistent formatting

### Large Number of Releases

If 10+ releases in one check:
- No special handling - render all with full analysis
- Trade-off: longer reports but comprehensive coverage
- Consider adding `max_releases_to_analyze` config option if problematic

### Tag Fetching Failures

If `gh repo clone -- --tags` fails:
- Log warning: "Failed to fetch tags, continuing with API-only mode"
- Don't fail entire check - GitHub API still works
- System continues with current behavior

### Database Tracking

`Repository` model fields unchanged:
- `last_release_tag`: most recent release tag
- `last_release_commit_hash`: commit hash of most recent release
- `last_release_check_time`: timestamp of last check

These track the most recent release processed, not all releases.

## Template Structure (repository_report.j2)

Replace existing release section with:

```jinja2
{% if new_releases %}
**{{ new_releases|length }} release{{ 's' if new_releases|length != 1 else '' }}**:

{% for release in new_releases %}
<details>
<summary>🚀 {{ release.title }} 🏷 {{ release.tag_name }}</summary>

{{ release.body }}

</details>

{{ release.ai_summary }}

<details>
<summary>Click to view detailed release analysis</summary>

{{ release.ai_detail }}

</details>

{% endfor %}

{% endif %}
```

**Key Details:**
- Release notes are markdown, render correctly in final report
- Sort releases newest-first before passing to template
- Add `---` horizontal rule after releases to separate from commits section
- Commit section continues unchanged after releases

## Testing Strategy

### Unit Tests to Add/Modify

**1. `test_repo.py` - Git operations:**
- Test `clone_repo()` constructs correct gh command with `-- --tags`
- Mock subprocess call and verify command includes tags flag
- Test clone failures with `--tags` don't break flow

**2. `test_repo.py` - Release checking:**
- Test `check_releases()` returns flat list (no intermediate releases structure)
- Test with 0, 1, and multiple new releases
- Verify returned list has all expected fields for each release
- Test ordering is preserved (reversed later in reporter)

**3. `test_reporter.py` - AI analysis loop:**
- Mock Claude API to test individual calls per release
- Verify N releases result in N API calls
- Test one failed analysis doesn't stop others from being processed
- Verify structure of returned analyzed releases list

**4. Template rendering tests:**
- Create mock release data and verify template renders without errors
- Test edge cases: empty body, missing AI analysis, special characters in titles
- Verify plural/singular handling for "**1 release**" vs "**3 releases**"

### Existing Tests to Update

- Tests asserting "intermediate releases" structure
- Tests checking for single release banner

### Integration Testing

Manual verification by user - run full check cycle on real repositories and verify report output.

## Implementation Notes

### Configuration

No new config options needed. Existing release detection settings (drafts, pre-releases exclusion) remain unchanged.

### File Changes Summary

1. `src/progress/repo.py` - 2 changes:
   - Line ~512-522: Add `-- --tags` to `gh repo clone`
   - Line ~323-349: Simplify `check_releases()` to return flat list

2. `src/progress/reporter.py` - 1 change:
   - Modify release analysis to loop through releases individually
   - Sort releases newest-first
   - Handle per-release AI failures gracefully

3. `src/progress/templates/repository_report.j2` - 1 change:
   - Replace current release section with loop structure
   - Add section separator after releases

4. `tests/test_repo.py` - Add/modify tests for git operations and release checking

5. `tests/test_reporter.py` - Add tests for per-release AI analysis

### Breaking Changes

None. Output format changes, but API and configuration remain compatible.

### Performance Considerations

- More AI API calls when multiple releases exist (1 per release vs 1 per batch)
- Trade-off accepted: better granularity of analysis
- Rate limit handling already exists in codebase

### Backwards Compatibility

Existing reports in database unaffected. New reports use updated format.

## Design Principles

This design follows YAGNI by:
- Removing the complex "intermediate releases" concept
- Treating all releases consistently
- Adding minimal code (just `--tags` flag)
- Simplifying template logic with single loop

The focus is on clearer, more comprehensive reporting without unnecessary complexity.
