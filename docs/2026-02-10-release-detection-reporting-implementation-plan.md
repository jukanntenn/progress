# Release Detection and Reporting Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `--tags` flag to git clone operations and simplify release detection/reporting to show all new releases with individual AI analysis.

**Architecture:**
1. Modify `gh repo clone` command to pass `-- --tags` to git
2. Remove "intermediate releases" concept from `check_releases()`
3. Generate AI analysis for each release individually (not batch)
4. Update report template to loop through releases newest-first

**Tech Stack:** Python 3.12+, Click 8.3+, Jinja2 3.1+, GitPython 3.1.46+, PyGithub 2.8.1+

---

## Task 1: Add --tags Flag to gh Clone Command

**Files:**
- Modify: `src/progress/repo.py:512-524` (clone_repo method)
- Test: `tests/test_repo.py` (add new test)

### Step 1: Write failing test for --tags flag

Add this test to `tests/test_repo.py`:

```python
def test_clone_includes_tags_flag(self):
    """Test that clone command includes --tags flag"""
    model = Mock(spec=Repository)
    model.url = "https://github.com/owner/repo.git"
    model.branch = "main"
    model.last_commit_hash = None

    git = Mock(spec=GitClient)
    git.workspace_dir = Path("/tmp/workspace")

    config = Mock(spec=Config)
    github_config = Mock()
    github_config.gh_timeout = 300
    config.github = github_config

    repo = Repo(model, git, config, gh_token="test_token")
    repo.repo_path = Path("/tmp/workspace/owner_repo")

    with patch.object(repo, "_run_command") as mock_run:
        repo.clone_repo("https://github.com/owner/repo.git", "main")

        call_args = mock_run.call_args[0][0]
        assert "--" in call_args
        assert "--tags" in call_args
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_repo.py::TestRepo::test_clone_includes_tags_flag -v`

Expected: FAIL - `--tags` flag not in command

### Step 3: Implement --tags flag in clone_repo

In `src/progress/repo.py`, modify the `clone_repo` method around line 512-524.

**Current code:**
```python
cmd = [
    CMD_GH,
    "repo",
    "clone",
    url,
    str(repo_path),
    "--",
    "--branch",
    branch,
    "--single-branch",
]
```

**New code:**
```python
cmd = [
    CMD_GH,
    "repo",
    "clone",
    url,
    str(repo_path),
    "--",
    "--branch",
    branch,
    "--single-branch",
    "--tags",
]
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_repo.py::TestRepo::test_clone_includes_tags_flag -v`

Expected: PASS

### Step 5: Commit

```bash
git add src/progress/repo.py tests/test_repo.py
git commit -m "feat: add --tags flag to gh clone command"
```

---

## Task 2: Simplify check_releases to Return Flat List

**Files:**
- Modify: `src/progress/repo.py:323-470` (check_releases and related methods)
- Test: `tests/test_repo.py` (update existing tests)

### Step 1: Update test expectations

Find tests that assert `intermediate_releases` structure. Update them to expect flat list.

First, check what release-related tests exist:

Run: `uv run pytest tests/test_repo.py -v -k release`

If there are tests expecting `intermediate_releases`, modify them. If not, add new test:

```python
def test_check_releases_returns_flat_list(self):
    """Test that check_releases returns list of all new releases"""
    from datetime import datetime, timezone

    model = Mock(spec=Repository)
    model.url = "https://github.com/owner/repo.git"
    model.last_release_tag = "v1.0.0"
    model.last_release_commit_hash = "abc123"
    model.last_release_check_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    git = Mock(spec=GitClient)
    git.workspace_dir = Path("/tmp/workspace")
    git.get_commit_diff = Mock(return_value="diff content")

    github_client = Mock()
    github_client.list_releases = Mock(return_value=[
        {"tagName": "v1.3.0", "name": "v1.3.0", "publishedAt": "2024-01-03T00:00:00Z"},
        {"tagName": "v1.2.0", "name": "v1.2.0", "publishedAt": "2024-01-02T00:00:00Z"},
        {"tagName": "v1.1.0", "name": "v1.1.0", "publishedAt": "2024-01-01T12:00:00Z"},
    ])
    github_client.get_release_commit = Mock(return_value="def456")
    github_client.get_release_body = Mock(return_value="Release notes")

    config = Mock(spec=Config)

    repo = Repo(model, git, config, github_client=github_client)
    repo.github_client = github_client
    repo.git = git

    result = repo.check_releases()

    assert result is not None
    assert "releases" in result
    assert len(result["releases"]) == 3
    assert result["releases"][0]["tag_name"] == "v1.3.0"
    assert result["releases"][1]["tag_name"] == "v1.2.0"
    assert result["releases"][2]["tag_name"] == "v1.1.0"
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_repo.py::TestRepo::test_check_releases_returns_flat_list -v`

Expected: FAIL - current implementation has different structure

### Step 3: Rewrite check_releases methods

Replace the entire release checking logic in `src/progress/repo.py` starting at line 323.

**Current structure:**
- `check_releases()` returns dict with `latest_release` and `intermediate_releases`
- `_handle_first_release_check()` and `_handle_incremental_release_check()` have complex logic

**New structure:**

Replace all three methods (`check_releases`, `_handle_first_release_check`, `_handle_incremental_release_check`) with simplified version:

```python
def check_releases(self) -> Optional[dict]:
    """Check for new GitHub releases.

    Returns:
        Dict with list of release data, or None if no new releases:
        - releases: list of dicts with tag_name, name, notes, published_at, commit_hash
    """
    try:
        owner, repo_name = self.slug.split("/")
        releases = self.github_client.list_releases(owner, repo_name)
    except GitException as e:
        logger.warning(f"Failed to check releases for {self.slug}: {e}")
        return None

    if not releases:
        logger.debug(f"No releases found for {self.slug}")
        return None

    new_releases = []
    last_check_time = self.model.last_release_check_time

    from datetime import datetime

    for r in releases:
        published_at_str = r.get("publishedAt")
        if published_at_str:
            try:
                published_at = datetime.fromisoformat(published_at_str.replace("Z", "+00:00"))
                if last_check_time is None or published_at > last_check_time:
                    try:
                        commit_hash = self.github_client.get_release_commit(owner, repo_name, r["tagName"])
                    except GitException as e:
                        logger.warning(f"Failed to get commit hash for {r['tagName']}: {e}")
                        commit_hash = None

                    try:
                        notes = self.github_client.get_release_body(owner, repo_name, r["tagName"])
                    except GitException as e:
                        logger.warning(f"Failed to get release notes for {r['tagName']}: {e}")
                        notes = ""

                    new_releases.append({
                        "tag_name": r["tagName"],
                        "title": r["name"],
                        "notes": notes,
                        "published_at": r["publishedAt"],
                        "commit_hash": commit_hash,
                    })
            except (ValueError, TypeError):
                logger.debug(f"Could not parse publishedAt: {published_at_str}")
                continue

    if not new_releases:
        return None

    return {"releases": new_releases}
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_repo.py::TestRepo::test_check_releases_returns_flat_list -v`

Expected: PASS

### Step 5: Update other affected tests

Run all repo tests to find others that need updating:

Run: `uv run pytest tests/test_repo.py -v`

Update any tests that reference `intermediate_releases`, `latest_release`, `diff_from`, `diff_to`, or `diff_content`.

### Step 6: Commit

```bash
git add src/progress/repo.py tests/test_repo.py
git commit -m "refactor: simplify release detection to return flat list"
```

---

## Task 3: Update RepositoryManager to Handle Individual Release Analysis

**Files:**
- Modify: `src/progress/repository.py:240-280` (check_repository method)
- Test: `tests/test_repo.py` or create new test file

### Step 1: Write test for individual release analysis

Create `tests/test_repository.py` or add to existing file:

```python
def test_analyze_releases_individually(self):
    """Test that each release gets analyzed separately"""
    release_data = {
        "releases": [
            {"tag_name": "v1.3.0", "title": "v1.3.0", "notes": "Notes for v1.3", "published_at": "2024-01-03T00:00:00Z"},
            {"tag_name": "v1.2.0", "title": "v1.2.0", "notes": "Notes for v1.2", "published_at": "2024-01-02T00:00:00Z"},
        ]
    }

    analyzer = Mock()
    analyzer.analyze_releases = Mock(side_effect=[
        ("summary v1.3", "detail v1.3"),
        ("summary v1.2", "detail v1.2"),
    ])

    manager = RepositoryManager(Mock(), Mock())
    manager.analyzer = analyzer

    result = manager._analyze_all_releases("owner/repo", "main", release_data)

    assert len(result) == 2
    assert result[0]["tag_name"] == "v1.3.0"
    assert result[0]["ai_summary"] == "summary v1.3"
    assert result[0]["ai_detail"] == "detail v1.3"
    assert result[1]["tag_name"] == "v1.2.0"
    assert result[1]["ai_summary"] == "summary v1.2"
    assert result[1]["ai_detail"] == "detail v1.2"

    assert analyzer.analyze_releases.call_count == 2
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_repository.py::test_analyze_releases_individually -v`

Expected: FAIL - method doesn't exist yet

### Step 3: Add helper method for individual release analysis

In `src/progress/repository.py`, add new method to RepositoryManager:

```python
def _analyze_all_releases(self, repo_name: str, branch: str, release_data: dict) -> list:
    """Analyze all releases individually.

    Args:
        repo_name: Repository name
        branch: Branch name
        release_data: Dict with releases list

    Returns:
        List of release dicts with added ai_summary and ai_detail fields
    """
    analyzed_releases = []

    for release in release_data["releases"]:
        single_release_data = {
            "is_first_check": False,
            "latest_release": {
                "tag": release["tag_name"],
                "name": release["title"],
                "notes": release["notes"],
                "published_at": release["published_at"],
                "commit_hash": release.get("commit_hash"),
            },
            "intermediate_releases": [],
            "diff_content": None,
        }

        try:
            summary, detail = self.analyzer.analyze_releases(
                repo_name, branch, single_release_data
            )
        except Exception as e:
            self.logger.warning(f"Failed to analyze release {release['tag_name']}: {e}")
            summary = f"**AI analysis unavailable for {release['tag_name']}**"
            detail = f"**Release Information:**\\n\\n- **Tag:** {release['tag_name']}\\n- **Name:** {release.get('title', release['tag_name'])}\\n- **Published:** {release.get('published_at', 'unknown')}\\n\\n{release.get('notes', '')}"

        analyzed_releases.append({
            **release,
            "ai_summary": summary,
            "ai_detail": detail,
        })

    return analyzed_releases
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_repository.py::test_analyze_releases_individually -v`

Expected: PASS

### Step 5: Update check_repository to use new method

In `src/progress/repository.py`, modify the `check_repository` method around line 240-280.

**Find the release handling code:**
```python
release_data = None
release_summary = ""
release_detail = ""

if repo.check_releases_enabled:
    release_data = repo_obj.check_releases()
    if release_data:
        # ... existing analysis logic
```

**Replace with:**
```python
release_data = None
releases_list = None

if repo.check_releases_enabled:
    release_data = repo_obj.check_releases()
    if release_data:
        self.logger.info(f"Found {len(release_data['releases'])} new releases, analyzing...")
        releases_list = self._analyze_all_releases(str(repo.name), str(repo.branch), release_data)

        latest = release_data["releases"][0]
        commit_hash = latest.get("commit_hash")
        if commit_hash:
            repo_obj.update_releases(latest["tag_name"], commit_hash)
```

### Step 6: Update Report data model

Modify the RepositoryReport class (around line 50-70) to use the new structure:

**Current:**
```python
release_data: dict | None = None
release_summary: str = ""
release_detail: str = ""
```

**New:**
```python
releases: list | None = None
```

### Step 7: Run tests to verify

Run: `uv run pytest tests/test_repository.py -v`

Expected: PASS (may need to update additional tests)

### Step 8: Commit

```bash
git add src/progress/repository.py tests/test_repository.py
git commit -m "refactor: analyze each release individually"
```

---

## Task 4: Update Report Template

**Files:**
- Modify: `src/progress/templates/repository_report.j2:5-32`

### Step 1: Update template structure

Replace the entire release section in `src/progress/templates/repository_report.j2` (lines 5-32):

**Current:**
```jinja2
{% if report.release_data %}
┌─────────────────────────────────────────────────────────────────┐
│ 🚀 **New Release**: {{ report.release_data.latest_release.tag }}         │
│ Published: {{ report.release_data.latest_release.published_at }}         │
└─────────────────────────────────────────────────────────────────┘

{{ report.release_summary }}

<details>
<summary>{{ _("Click to view detailed release analysis") }}</summary>

{{ report.release_detail }}

{% if report.release_data.intermediate_releases %}
### Other releases since last check
{% for r in report.release_data.intermediate_releases[:5] %}
**{{ r.tag }}** ({{ r.published_at }})
{{ r.notes | truncate(200) if r.notes else _("No release notes provided.") }}

{% endfor %}
{% if report.release_data.intermediate_releases | length > 5 %}
*...and {{ report.release_data.intermediate_releases | length - 5 }} more releases*
{% endif %}
{% endif %}

</details>

{% endif %}
```

**New:**
```jinja2
{% if report.releases %}
**{{ report.releases|length }} release{{ 's' if report.releases|length != 1 else '' }}**:

{% for release in report.releases %}
<details>
<summary>🚀 {{ release.title }} 🏷 {{ release.tag_name }}</summary>

{{ release.notes }}

</details>

{{ release.ai_summary }}

<details>
<summary>{{ _("Click to view detailed release analysis") }}</summary>

{{ release.ai_detail }}

</details>

{% endfor %}

{% endif %}
```

### Step 2: Update RepositoryReport to pass releases

In `src/progress/repository.py`, modify where RepositoryReport is created (around line 320-340):

**Find:**
```python
RepositoryReport(
    ...
    release_data=release_data,
    release_summary=release_summary,
    release_detail=release_detail,
)
```

**Replace with:**
```python
RepositoryReport(
    ...
    releases=releases_list,
)
```

### Step 3: Test template rendering

Create simple test or manual verification:

```bash
cat > test_template.py << 'EOF'
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("src/progress/templates"))
template = env.get_template("repository_report.j2")

class MockReport:
    def __init__(self):
        self.repo_name = "test/repo"
        self.repo_web_url = "https://github.com/test/repo"
        self.branch = "main"
        self.releases = [
            {
                "tag_name": "v1.3.0",
                "title": "Release v1.3.0",
                "notes": "New features and bug fixes",
                "ai_summary": "**Summary of v1.3.0**",
                "ai_detail": "## Details of v1.3.0",
            },
            {
                "tag_name": "v1.2.0",
                "title": "Release v1.2.0",
                "notes": "More updates",
                "ai_summary": "**Summary of v1.2.0**",
                "ai_detail": "## Details of v1.2.0",
            },
        ]
        self.commit_count = 0
        self.commit_messages = []
        self.analysis_summary = ""
        self.analysis_detail = ""
        self.truncated = False

result = template.render(report=MockReport())
print(result)
EOF

uv run python test_template.py
```

Expected: Output shows both releases with proper formatting

### Step 4: Commit

```bash
rm test_template.py
git add src/progress/templates/repository_report.j2 src/progress/repository.py
git commit -m "refactor: update report template for multiple releases"
```

---

## Task 5: Sort Releases Newest-First

**Files:**
- Modify: `src/progress/repository.py` (in _analyze_all_releases method)

### Step 1: Add test for sorting

Add to `tests/test_repository.py`:

```python
def test_releases_sorted_newest_first(self):
    """Test that releases are sorted newest first"""
    release_data = {
        "releases": [
            {"tag_name": "v1.1.0", "published_at": "2024-01-01T00:00:00Z"},
            {"tag_name": "v1.3.0", "published_at": "2024-01-03T00:00:00Z"},
            {"tag_name": "v1.2.0", "published_at": "2024-01-02T00:00:00Z"},
        ]
    }

    analyzer = Mock()
    analyzer.analyze_releases = Mock(return_value=("summary", "detail"))

    manager = RepositoryManager(Mock(), Mock())
    manager.analyzer = analyzer

    result = manager._analyze_all_releases("owner/repo", "main", release_data)

    assert result[0]["tag_name"] == "v1.3.0"
    assert result[1]["tag_name"] == "v1.2.0"
    assert result[2]["tag_name"] == "v1.1.0"
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_repository.py::test_releases_sorted_newest_first -v`

Expected: FAIL - no sorting currently

### Step 3: Add sorting to _analyze_all_releases

In `src/progress/repository.py`, update `_analyze_all_releases` to sort before analyzing:

**Add at the beginning of the method:**
```python
from datetime import datetime

def _analyze_all_releases(self, repo_name: str, branch: str, release_data: dict) -> list:
    """Analyze all releases individually.

    Args:
        repo_name: Repository name
        branch: Branch name
        release_data: Dict with releases list

    Returns:
        List of release dicts with added ai_summary and ai_detail fields
    """
    releases = release_data["releases"]

    releases.sort(key=lambda r: datetime.fromisoformat(r["published_at"].replace("Z", "+00:00")), reverse=True)

    analyzed_releases = []

    for release in releases:
        # ... rest of method unchanged
```

### Step 4: Run test to verify it passes

Run: `uv run pytest tests/test_repository.py::test_releases_sorted_newest_first -v`

Expected: PASS

### Step 5: Commit

```bash
git add src/progress/repository.py tests/test_repository.py
git commit -m "feat: sort releases newest-first in reports"
```

---

## Task 6: Update Release Analysis Prompt Template

**Files:**
- Modify: `src/progress/templates/release_analysis_prompt.j2`

### Step 1: Simplify prompt for single release

The prompt needs to handle only one release at a time. Simplify `src/progress/templates/release_analysis_prompt.j2`:

**Current:** Has logic for first_check, intermediate_releases, etc.

**New simplified version:**
```jinja2
You are analyzing a GitHub release for a repository.

**Repository**: {{ repo_name }}
**Branch**: {{ branch }}

**Release**: {{ release_data.latest_release.tag }}
{% if release_data.latest_release.name %}**Name**: {{ release_data.latest_release.name }}{% endif %}
**Published**: {{ release_data.latest_release.published_at }}

### Release Notes

{{ release_data.latest_release.notes if release_data.latest_release.notes else "No release notes provided." }}

{% if release_data.diff_content %}
### Code Changes

The following diff shows code changes related to this release:

```
{{ release_data.diff_content }}
```
{% endif %}

## Your Task

Analyze this release and provide:

1. **Executive Summary** (2-3 sentences): What's the main purpose of this release?

2. **Key Changes**: Categorize changes into:
   - 🎁 **New Features**: What new capabilities are added?
   - 🐛 **Bug Fixes**: What issues are resolved?
   - ⚠️ **Breaking Changes**: What changes could break existing functionality?
   - 🔧 **Improvements**: What has been improved?
   - 📚 **Documentation**: What documentation changes are included?

3. **Upgrade Guidance**:
   - Should users upgrade? Why/why not?
   - Are there any migration steps needed?
   - What are the risks or concerns?

4. **Impact Assessment**: Low/Medium/High impact for users depending on this project.

{% if language %}
**Important**: Write your analysis in {{ language }}.
{% endif %}

## Output Format

**CRITICAL**: You MUST respond with a valid JSON object only. Do not include any markdown formatting, code blocks, or explanatory text outside the JSON structure.

Your response must be in this exact JSON format:

```json
{
  "summary": "A 2-3 sentence executive summary of the release",
  "detail": "Full detailed analysis including key changes, upgrade guidance, and impact assessment in markdown format"
}
```

Requirements:
- `summary`: A concise 2-3 sentence overview suitable for quick reading
- `detail`: Comprehensive markdown analysis with all sections (key changes categorized with emojis, upgrade guidance, impact assessment, etc.)
- Both fields must be non-empty strings
- Output ONLY the JSON object, nothing else
- Do not wrap the JSON in markdown code blocks
- Do not add any explanatory text before or after the JSON

Example:
{"summary":"This release adds dark mode support and fixes 5 critical bugs.","detail":"## 🎦 New Features\\n\\n- **Dark Mode**: Full dark theme support across all pages\\n\\n## 🐛 Bug Fixes\\n\\n- Fixed login issue with Safari browsers\\n- Resolved memory leak in dashboard\\n..."}
```

### Step 2: Commit

```bash
git add src/progress/templates/release_analysis_prompt.j2
git commit -m "refactor: simplify release analysis prompt for single release"
```

---

## Task 7: Add Section Separator After Releases

**Files:**
- Modify: `src/progress/templates/repository_report.j2`

### Step 1: Add horizontal rule after releases

In the template, add `---` after the releases loop and before the commits section:

**Find the end of releases section:**
```jinja2
{% endfor %}

{% endif %}
{% if report.commit_count > 0 %}
```

**Add separator:**
```jinja2
{% endfor %}

---
{% endif %}
{% if report.commit_count > 0 %}
```

### Step 2: Test rendering

Use the same test script from Task 4 to verify.

### Step 3: Commit

```bash
git add src/progress/templates/repository_report.j2
git commit -m "style: add section separator after releases"
```

---

## Task 8: Run Full Test Suite

### Step 1: Run all tests

Run: `uv run pytest -v`

Expected: All tests pass (240 tests)

### Step 2: Fix any remaining issues

If tests fail, update them to match the new structure.

### Step 3: Final commit if needed

```bash
git add tests/
git commit -m "test: update tests for new release structure"
```

---

## Task 9: Manual Integration Testing

### Step 1: Test on real repository

Run a manual check on a repository with releases:

```bash
uv run progress check -c config/simple.toml
```

Verify:
- Multiple releases show up with individual analysis
- Releases are ordered newest-first
- Each release has collapsible notes and detailed analysis
- Section separator appears after releases

### Step 2: Verify report output

Check the generated report file matches expected format.

### Step 3: Clean up

Remove any test data or temporary files.

---

## Task 10: Update Documentation

### Step 1: Update design doc with completion status

Edit `docs/2026-02-10-release-detection-and-reporting-improvements-design.md`:

Add at the top:
```markdown
**Status:** ✅ Completed 2026-02-10
```

Add implementation notes section at the end:
```markdown
## Implementation Notes

- Implemented in branch: release-detection-improvements
- All tests passing (240 tests)
- Manual integration testing completed
```

### Step 2: Commit documentation update

```bash
git add docs/2026-02-10-release-detection-and-reporting-improvements-design.md
git commit -m "docs: mark release detection improvements as complete"
```

---

## Summary

This implementation plan:
1. ✅ Adds `--tags` flag to git clone operations
2. ✅ Simplifies release detection by removing intermediate releases concept
3. ✅ Generates individual AI analysis for each release
4. ✅ Updates template to show all releases newest-first with consistent formatting
5. ✅ Maintains backwards compatibility (no breaking changes)
6. ✅ Follows TDD with tests written first
7. ✅ Commits frequently for easy rollback

**Files Modified:**
- `src/progress/repo.py` - clone command, check_releases logic
- `src/progress/repository.py` - release analysis loop, data model
- `src/progress/templates/repository_report.j2` - multi-release display
- `src/progress/templates/release_analysis_prompt.j2` - simplified prompt
- `tests/test_repo.py` - updated tests
- `tests/test_repository.py` - new tests

**Estimated Time:** 2-3 hours for all tasks
