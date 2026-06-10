# Proposal Module Design Specification

Clean-room redesign for tracking EIP, ERC, PEP, Rust RFC, and Django DEP proposals.

---

## 1. Design Principles

1. **Dependency injection** — All external dependencies (DB, git, AI, clock) are injected via constructor. No global state, no import-time side effects. Enables easy mocking in tests.
2. **High cohesion, low coupling** — Business logic is fully encapsulated within the `proposal` module. Only minimal interfaces are exposed to external consumers (CLI, API). Internal details (parsers, status maps, DB schema) are not visible outside the module.
3. **Pure functions first** — Status normalization, notification decisions, and template selection are pure functions with no I/O. Testable without mocks.
4. **No backward compatibility** — This is a complete rewrite. Old code, DB tables, and config formats are replaced entirely.

### Module Boundary

```
proposal module exposes:
  ├── ProposalKind (enum)
  ├── ProposalStatus (enum)
  ├── ProposalReport (NamedTuple)
  └── ProposalTracker.check(kind) → list[ProposalReport]
  └── ProposalTracker.check_all(kinds) → list[ProposalReport]

proposal module hides:
  ├── Parsers (internal)
  ├── Status maps (internal)
  ├── DB models (internal)
  ├── KIND_CONFIGS (internal)
  └── analysis helper (internal)
```

External consumers (CLI, API) only depend on the public surface. They do not import parsers, models, or status logic.

### Constructor Injection

```python
class ProposalTracker:
    def __init__(
        self,
        analyzer: Analyzer,          # AI analysis (mockable)
        git_client: GitClient,       # Git operations (mockable)
        clock: Callable[[], datetime], # Time source (mockable)
    ): ...

    def check(self, kind: ProposalKind) -> list[ProposalReport]: ...

    def check_all(
        self,
        kinds: list[ProposalKind],
        concurrency: int = 1,
    ) -> list[ProposalReport]: ...
```

The DB is accessed through Peewee models internally — no repository protocol abstraction needed for a single-implementation tool. Tests use in-memory SQLite with the same models.

---

## 2. Architecture Overview

```
src/progress/contrib/proposal/
├── __init__.py      # Public API: ProposalKind, ProposalStatus, ProposalReport, ProposalTracker
├── types.py         # ProposalKind, ProposalStatus enums + KIND_CONFIGS (internal)
├── status.py        # STATUS_MAPS, should_notify(), get_analysis_template() (internal)
├── parser.py        # ProposalParser ABC + per-kind implementations (internal)
├── models.py        # Peewee ORM models (internal)
├── analysis.py      # AI analysis helper (internal)
└── tracker.py       # ProposalTracker class + core workflow
```

Data flow:

```
Config (kind list) → ProposalTracker.check(kind)
                       ├── KIND_CONFIGS[kind] → repo_url, branch, parser
                       ├── parser.parse() → ParsedProposal
                       ├── DB: read old proposal → compare status
                       ├── status.normalize() + should_notify()
                       ├── analysis.run() (if needed) → summary, detail
                       └── DB: upsert proposal → return ProposalReport
```

---

## 3. ProposalKind

Each kind has fixed attributes hardcoded in the module. These values rarely change and are not user-configurable.

```python
class ProposalKind(StrEnum):
    EIP = "eip"
    ERC = "erc"
    PEP = "pep"
    RFC = "rfc"
    DEP = "dep"
```

```python
class KindConfig(NamedTuple):
    repo_url: str
    branch: str
    proposal_dir: str
    file_pattern: list[str]

KIND_CONFIGS: dict[ProposalKind, KindConfig] = {
    ProposalKind.EIP: KindConfig(
        repo_url="https://github.com/ethereum/EIPs",
        branch="main",
        proposal_dir="EIPS",
        file_pattern=["eip-*.md"],
    ),
    ProposalKind.ERC: KindConfig(
        repo_url="https://github.com/ethereum/ercs",
        branch="main",
        proposal_dir="ERCS",
        file_pattern=["erc-*.md"],
    ),
    ProposalKind.PEP: KindConfig(
        repo_url="https://github.com/python/peps",
        branch="main",
        proposal_dir="",
        file_pattern=["pep-*.rst"],
    ),
    ProposalKind.RFC: KindConfig(
        repo_url="https://github.com/rust-lang/rfcs",
        branch="master",
        proposal_dir="text",
        file_pattern=["*.md"],
    ),
    ProposalKind.DEP: KindConfig(
        repo_url="https://github.com/django/deps",
        branch="main",
        proposal_dir="",
        file_pattern=["*.rst", "*.md"],
    ),
}
```

ERC is separated from EIP because they live in different repositories with different file patterns, despite sharing the same YAML frontmatter format.

EIPParser handles both EIP and ERC (same format). The `ProposalKind` determines which repo and files to scan; the parser does not need to know which kind it is parsing.

---

## 4. ProposalStatus & Status Mapping

### Normalized Status

A unified status vocabulary that all proposal types map to:

```python
class ProposalStatus(StrEnum):
    DRAFT = "draft"          # Under development
    REVIEW = "review"        # Under formal review
    ACCEPTED = "accepted"    # Approved, implementation in progress
    FINAL = "final"          # Completed standard (terminal)
    ACTIVE = "active"        # Living document, continuously updated (terminal)
    STAGNANT = "stagnant"    # Inactive, may be resurrected
    DEFERRED = "deferred"    # Explicitly postponed
    WITHDRAWN = "withdrawn"  # Author withdrew (terminal)
    REJECTED = "rejected"    # Rejected (terminal)
    SUPERSEDED = "superseded" # Replaced by another proposal (terminal)
    MOVED = "moved"          # Relocated to another repository (terminal)
    UNKNOWN = "unknown"      # Cannot determine status (terminal)

TERMINAL_STATUSES = frozenset({
    ProposalStatus.FINAL, ProposalStatus.ACTIVE,
    ProposalStatus.WITHDRAWN, ProposalStatus.REJECTED,
    ProposalStatus.SUPERSEDED, ProposalStatus.MOVED, ProposalStatus.UNKNOWN,
})
```

### Status Maps

Per-kind mapping from raw status strings to normalized statuses:

| Raw Status | EIP/ERC | PEP | RFC | DEP |
|---|---|---|---|---|
| Draft | DRAFT | DRAFT | — | DRAFT |
| Review | REVIEW | — | — | — |
| Last Call | REVIEW | — | — | — |
| Accepted | — | ACCEPTED | — | ACCEPTED |
| Provisional | — | ACCEPTED | — | — |
| Final | FINAL | FINAL | — | FINAL |
| Active | — | ACTIVE | — | — |
| Living | ACTIVE | — | — | — |
| Stagnant | STAGNANT | — | — | — |
| Deferred | — | DEFERRED | — | — |
| Withdrawn | WITHDRAWN | WITHDRAWN | — | WITHDRAWN |
| Rejected | — | REJECTED | — | REJECTED |
| April Fool! | — | REJECTED | — | — |
| Superseded | — | SUPERSEDED | — | SUPERSEDED |
| Moved | MOVED | — | — | — |
| (file in text/) | — | — | ACCEPTED | — |
| (anything else) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |

RFC files have no status field. Files present in `text/` are treated as ACCEPTED (their PR was merged).

```python
def normalize(kind: ProposalKind, raw_status: str) -> ProposalStatus:
    if kind == ProposalKind.RFC:
        return ProposalStatus.ACCEPTED
    return STATUS_MAPS[kind].get(raw_status, ProposalStatus.UNKNOWN)
```

---

## 5. Status Transitions

### Transition Diagram

```
                        Non-terminal                        Terminal
                        ────────────                        ─────────

  None ─────────→  DRAFT ──→ REVIEW ──→ ACCEPTED ──→ FINAL ●
  (new proposal)     │ ◄───┘     │                   ACTIVE ●
                     │            │
                     ├────→ STAGNANT ◄──────┐
                     │          │            │     ──→ WITHDRAWN ●  [notify]
                     │          └──→ DRAFT/  │     ──→ REJECTED ●   [notify]
                     │              REVIEW   │     ──→ SUPERSEDED ●
                     │          (resurrect) │     ──→ MOVED ●
                     └────→ DEFERRED ──→ DRAFT/   ──→ UNKNOWN ●
                                  REVIEW
                               (resurrect)

  Same status:  DRAFT → DRAFT  (content modified only, no notify)
```

### Decision Rules

All business decisions derive from `(old_status, new_status)` comparison. No separate event type is needed.

**Should we notify?**

| Condition | Notify? | Reason |
|---|---|---|
| `old_status is None` | Yes | New proposal discovered |
| `old_status == new_status` | No | Content-only change |
| `new_status ∈ {FINAL, ACTIVE, ACCEPTED}` | Yes | Proposal accepted/finalized |
| `new_status == REJECTED` | Yes | Proposal rejected |
| `new_status == WITHDRAWN` | Yes | Proposal withdrawn |
| Any other transition | No | Low-priority transition |

```python
NOTIFY_STATUSES = frozenset({
    ProposalStatus.FINAL, ProposalStatus.ACTIVE, ProposalStatus.ACCEPTED,
    ProposalStatus.WITHDRAWN, ProposalStatus.REJECTED,
})

def should_notify(old_status: ProposalStatus | None, new_status: ProposalStatus) -> bool:
    if old_status is None:
        return True
    if old_status == new_status:
        return False
    return new_status in NOTIFY_STATUSES
```

**Which AI analysis template?**

| Condition | Template | Input |
|---|---|---|
| `old_status is None` | proposal_new_prompt | Full text |
| `old_status == new_status` | proposal_content_modified_prompt | Git diff |
| `new_status ∈ {FINAL, ACTIVE, ACCEPTED}` | proposal_accepted_prompt | Full text |
| `new_status == REJECTED` | proposal_rejected_prompt | Full text |
| `new_status == WITHDRAWN` | proposal_withdrawn_prompt | Full text |
| Other transition | proposal_status_change_prompt | Full text |

```python
def get_analysis_template(old_status: ProposalStatus | None, new_status: ProposalStatus) -> str:
    if old_status is None:
        return "proposal_new_prompt.j2"
    if old_status == new_status:
        return "proposal_content_modified_prompt.j2"
    return {
        ProposalStatus.FINAL: "proposal_accepted_prompt.j2",
        ProposalStatus.ACTIVE: "proposal_accepted_prompt.j2",
        ProposalStatus.ACCEPTED: "proposal_accepted_prompt.j2",
        ProposalStatus.REJECTED: "proposal_rejected_prompt.j2",
        ProposalStatus.WITHDRAWN: "proposal_withdrawn_prompt.j2",
    }.get(new_status, "proposal_status_change_prompt.j2")
```

**Deleted file handling:**

When a proposal file is deleted from the repo:
- If current status is non-terminal → update to `WITHDRAWN` (notify)
- If current status is terminal → no change (administrative removal, no notify)

---

## 6. Database Schema

Two tables. `ProposalEvent` is removed — the event concept is derived from status comparison and does not need persistence.

### proposal_trackers

Stores runtime state per kind. Configuration (repo_url, branch, etc.) is hardcoded, not in DB.

```sql
CREATE TABLE proposal_trackers (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL UNIQUE,
    last_seen_commit TEXT,
    last_check_time  TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
```

| Column | Purpose |
|---|---|
| `kind` | Identifies which proposal system. UNIQUE — each kind is tracked once. |
| `last_seen_commit` | `None` = first run (initial check). Otherwise the commit hash from the previous check. |
| `last_check_time` | When the tracker was last run. |

### proposals

Stores the current snapshot of each proposal. Replaces the 4 separate tables (eips, rust_rfcs, peps, django_deps).

```sql
CREATE TABLE proposals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracker_id  INTEGER NOT NULL REFERENCES proposal_trackers(id) ON DELETE CASCADE,
    number      TEXT NOT NULL,
    title       TEXT,
    raw_status  TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE(tracker_id, number)
);
CREATE INDEX idx_proposals_tracker_id ON proposals(tracker_id);
```

| Column | Type | Purpose |
|---|---|---|
| `tracker_id` | FK | Links to proposal_trackers. Implies the kind (and thus repo_url, parser, etc.). |
| `number` | TEXT | Proposal identifier. TEXT (not INTEGER) to support future non-numeric schemes. Empty string if unparseable. |
| `title` | TEXT NULL | NULL for EIP Moved stubs (no title in frontmatter). Read for deleted-file notifications. |
| `raw_status` | TEXT | Original status string from file metadata. Empty string for RFCs (no status field). Used as context for AI analysis prompts. |
| `status` | TEXT | Normalized ProposalStatus value. Used for change detection and notification decisions. |

**Unique constraint**: `(tracker_id, number)` — each proposal number appears once per tracker.

**Note on RFC 2071**: This number has two files (one is a redirect stub). Without `file_path` in the unique key, the second overwrites the first. This is acceptable — it is the only known duplicate across 633 RFC files, and the redirect stub is not useful data.

---

## 7. Parser Design

### ParsedProposal

```python
class ParsedProposal(NamedTuple):
    number: str                  # "" if unparseable
    title: str | None            # None for EIP Moved stubs
    raw_status: str              # "" for RFCs
    file_path: str               # Relative path within repo
    full_text: str               # Full file content for AI analysis
    extra: dict[str, str]        # Type-specific metadata (category, topic, etc.)
```

### Parser ABC

```python
class ProposalParser(ABC):
    @abstractmethod
    def parse(self, file_path: str) -> ParsedProposal: ...

    @abstractmethod
    def extract_number(self, file_path: str) -> str: ...

    @abstractmethod
    def matches_pattern(self, file_path: str, pattern: str) -> bool: ...
```

### Implementations

| Parser | Handles | Metadata Source |
|---|---|---|
| `EIPParser` | EIP + ERC | YAML frontmatter |
| `PEPParser` | PEP | Plain `Key: Value` headers (scan up to 40 lines for long author lists) |
| `RFCParser` | RFC | Filename + first heading + bullet list fields. No status field. |
| `DEPParser` | DEP | RST field list (`:Key: Value`) or YAML frontmatter (Markdown files) |

**Key behaviors:**

- **EIPParser**: Handles both EIP and ERC (same format). Moved stubs (no title/author/type) set `title = None`, `raw_status = ""` — the parser does not raise on missing fields.
- **PEPParser**: Scans up to 40 lines for headers. Skips auxiliary directories (e.g. `pep-0001/`).
- **RFCParser**: Sets `raw_status = ""` since RFC files have no status field. All files in `text/` are ACCEPTED.
- **DEPParser**: Detects format from first line (`---` = YAML, otherwise RST field list). Sets `number = ""` for files without a number (e.g. `content-negotiation.rst`).

### Shared Parsing Utilities

```python
def parse_yaml_frontmatter(text: str) -> dict[str, str]
def parse_rst_field_list(text: str) -> dict[str, str]  # Handles RST titles, field lists, continuation lines
def parse_date(value: str) -> datetime | None
def compute_content_hash(text: str) -> str  # For ParsedProposal, not stored in DB
```

---

## 8. Tracker Core Workflow

### ProposalReport

Returned by `check()`, consumed by notification and reporting logic:

```python
class ProposalReport(NamedTuple):
    kind: ProposalKind
    number: str
    title: str | None
    old_status: ProposalStatus | None   # None = new proposal
    new_status: ProposalStatus
    file_path: str                      # Relative path in repo
    file_url: str                       # Link to file on GitHub
    commit_hash: str
    analysis_summary: str | None
    analysis_detail: str | None
```

### Core Flow

```
check(kind) → list[ProposalReport]:

    1. config = KIND_CONFIGS[kind]
    2. state = DB.get_or_create_tracker(kind)
    3. repo_path = clone_or_update(config.repo_url, config.branch)
    4. current_commit = git.get_head_commit(repo_path)

    5. If state.last_seen_commit is None:
         → initial_check(kind, config, state, repo_path, current_commit)

    6. If current_commit == state.last_seen_commit:
         state.last_check_time = now; save; return []

    7. changed_files = git.get_changed_files(repo_path, state.last_seen_commit, current_commit)
    8. filtered = filter_by(config.proposal_dir, config.file_pattern, changed_files)

    9. For each (change_type, rel_path) in filtered:
         If deleted → handle_deleted(kind, state.id, rel_path, current_commit)
         Else       → handle_changed(kind, config, state.id, repo_path, rel_path,
                                     state.last_seen_commit, current_commit)

    10. state.last_seen_commit = current_commit; save
    11. Return all ProposalReports
```

### Initial Check (First Run)

```
initial_check(kind, config, state, repo_path, current_commit):

    1. Scan all matching files in repo_path/config.proposal_dir
    2. Parse and upsert each to DB  (baseline snapshot, no notifications)
    3. Find the most recently created proposal (by git file creation date)
    4. Run AI analysis for that one proposal
    5. Return one ProposalReport as verification
    6. state.last_seen_commit = current_commit; save
```

On first run, every file is "new" to us, but generating notifications for hundreds of existing proposals would create noise. The initial scan establishes the baseline. One verification report (with `old_status=None`, so `should_notify` returns `True`) is returned per kind — this triggers a notification and proves the tracker is working. The remaining proposals are saved silently as the baseline snapshot.

### Handle Changed File

```
handle_changed(kind, config, tracker_id, repo_path, rel_path, old_commit, new_commit):

    1. parsed = parser.parse(abs_path)
    2. old = DB.get_proposal(tracker_id, parsed.number)
    3. new_status = normalize(kind, parsed.raw_status)
    4. old_status = old.status if old else None
    5. template = get_analysis_template(old_status, new_status)

    6. If template == content_modified:
         diff = git.get_file_diff(repo_path, old_commit, new_commit, rel_path)
         summary, detail = analysis.run(template, content=diff, ...)
       Else:
         summary, detail = analysis.run(template, content=parsed.full_text, ...)

    7. DB.upsert_proposal(tracker_id, parsed, new_status)
    8. Return ProposalReport(...)
```

### Handle Deleted File

```
handle_deleted(kind, tracker_id, rel_path, new_commit):

    1. number = parser.extract_number(rel_path)
    2. old = DB.get_proposal(tracker_id, number)
    3. If not old → return None (unknown proposal deleted)
    4. If old.status not in TERMINAL_STATUSES:
         old.status = WITHDRAWN; save
         return ProposalReport(new_status=WITHDRAWN)
    5. Else:
         return ProposalReport(new_status=old.status)  # terminal, no meaningful change
```

---

## 9. AI Analysis

Uses `ai.Analyzer` directly (no separate ProposalAnalyzer protocol). Jinja2 templates are selected by `get_analysis_template()` based on status comparison.

```python
def run_analysis(
    analyzer: Analyzer,
    template_name: str,
    kind: ProposalKind,
    number: str,
    title: str | None,
    old_raw_status: str | None,
    new_raw_status: str,
    content: str | None = None,     # Full text or diff
    language: str = "en",
) -> tuple[str, str]:               # (summary, detail)
```

The function renders a Jinja2 template with context variables (`kind`, `number`, `title`, `old_status`, `new_status`, `language`), then calls `analyzer.analyze(content, prompt, parser=AnalysisResultParser())` and returns the parsed `(summary, detail)` tuple.

On analysis failure (timeout, parse error, etc.), the function catches the exception, logs a warning, and returns `("", "")`. The tracker continues processing other proposals — analysis failure does not block the check flow.

---

## 10. Configuration

```toml
proposal_trackers = ["eip", "pep", "rfc", "dep"]
```

A list of `ProposalKind` values to enable. All repo details are hardcoded in `KIND_CONFIGS`. To disable a tracker, remove it from the list.

The `sync()` method from the current design is eliminated — there is nothing to sync. The tracker state record is created on first `check()` via `get_or_create`.

---

## 11. Migration

This is a clean-room rewrite with no backward compatibility. The following old artifacts are deleted entirely.

### Files to Delete

```
src/progress/contrib/proposal/
├── proposal_tracking.py      # Old tracker manager (400+ lines)
├── models.py                 # Old Peewee models (EIP, RustRFC, PEP, DjangoDEP, ProposalEvent)
├── analysis.py               # Old analysis module
└── proposal_parsers.py       # Old parser implementations
```

The files within `src/progress/contrib/proposal/` are replaced in-place. The directory path does not change.

### Database Tables to Drop

```sql
DROP TABLE IF EXISTS proposal_events;
DROP TABLE IF EXISTS eips;
DROP TABLE IF EXISTS rust_rfcs;
DROP TABLE IF EXISTS peps;
DROP TABLE IF EXISTS django_deps;
DROP TABLE IF EXISTS proposal_trackers;
```

New tables (`proposal_trackers`, `proposals`) are created with the schema from Section 6. No data migration — existing proposal data is not preserved.

### Code to Remove

| Location | What |
|---|---|
| `src/progress/enums.py` | `ProposalEventType` enum |
| `src/progress/config.py` | `ProposalTrackerConfig` Pydantic model |
| `src/progress/config.py` | `proposal_trackers` field on `Config` class |
| `src/progress/cli.py` | Import of `ProposalTrackerManager`, `TRACKER_REPO_URLS` |
| `src/progress/cli.py` | `_send_proposal_event_notification()` function |
| `src/progress/cli.py` | `_build_proposal_context()` function |
| `src/progress/cli.py` | `list_proposals` command |
| `src/progress/cli.py` | `list_proposal_events` command |
| `src/progress/cli.py` | `sync_proposal_trackers` command |
| `src/progress/db/__init__.py` | Old proposal table imports in `create_tables()` |
| `src/progress/db/__init__.py` | Old proposal table migration logic in `migrate_database()` |

### Config Format Change

```toml
# OLD — per-tracker config block
[[proposal_trackers]]
type = "eip"
repo_url = "https://github.com/ethereum/EIPs"
branch = "main"
proposal_dir = "EIPS"
file_pattern = "eip-*.md"
enabled = true

# NEW — simple list
proposal_trackers = ["eip", "pep", "rfc", "dep"]
```

### Templates to Keep

All `templates/proposal_*_prompt.j2` templates are reused as-is. The `proposal_events_report.j2` template is updated to use `ProposalReport` fields instead of `ProposalEventReport` fields.

---

## 12. Testability

### Dependency Injection for Testing

```python
# Unit test — all external dependencies mocked
def test_draft_to_final_notifies():
    tracker = ProposalTracker(
        analyzer=Mock(spec=Analyzer),      # No AI calls
        git_client=MockGitClient(),         # No real git operations
        clock=lambda: datetime(2024, 1, 1, tzinfo=UTC),
    )
    # Use in-memory SQLite for DB
    db = SqliteDatabase(":memory:")
    # ... setup test data, run check, assert results
```

All five external dependencies are injectable:
- **Analyzer** — Mock for unit tests, real `ai.Analyzer` for integration tests
- **GitClient** — Mock for unit tests, local test repos for integration tests
- **Clock** — Fixed datetime for deterministic `detected_at` values
- **Database** — In-memory SQLite for unit tests, file-based for integration tests
- **Parsers** — Tested independently with file fixtures, injected per kind via KIND_CONFIGS

### Status Logic (Pure Functions — No Mocks Needed)

```
test_eip_draft_normalizes_to_DRAFT
test_eip_last_call_normalizes_to_REVIEW
test_pep_april_fool_normalizes_to_REJECTED
test_rfc_always_ACCEPTED
test_unknown_status_normalizes_to_UNKNOWN

test_notify_new_proposal
test_notify_draft_to_final
test_notify_draft_to_withdrawn
test_no_notify_draft_to_review
test_no_notify_same_status
test_no_notify_review_to_stagnant

test_template_new_proposal
test_template_content_modified
test_template_accepted
test_template_rejected
test_template_withdrawn
test_template_generic_status_change
```

### Parser Edge Cases (File Fixtures — No Mocks Needed)

```
test_eip_moved_stub_title_is_none
test_eip_moved_stub_raw_status_is_Moved
test_pep_deep_headers_30_plus_lines
test_pep_auxiliary_directory_skipped
test_rfc_no_status_raw_empty
test_rfc_redirect_stub_detected_by_size
test_dep_rst_field_list_format
test_dep_yaml_frontmatter_format
test_dep_no_number_number_is_empty_string
test_dep_header_directory_mismatch_uses_header
```

### Tracker Core Flow (Mocked Git + In-Memory DB)

```
test_initial_check_saves_all_proposals_to_db
test_initial_check_returns_one_verification_report
test_initial_check_empty_repo_returns_no_reports
test_initial_check_updates_last_seen_commit

test_incremental_detect_status_change_draft_to_final
test_incremental_detect_content_modified_same_status
test_incremental_no_change_same_commit_returns_empty
test_incremental_new_file_creates_proposal_and_notifies
test_incremental_updates_last_seen_commit

test_deleted_nonterminal_becomes_withdrawn
test_deleted_terminal_no_status_change
test_deleted_unknown_file_returns_none

test_parse_error_skipped_gracefully
test_analysis_failure_does_not_block_check
```

### Test Helpers

Unit tests share helper functions to reduce mock setup repetition:

```python
def _mock_analyzer(**overrides) -> Mock       # Default return_value, overrides per-attribute
def _mock_git(tmp_path, commit, **overrides)  # Default workspace_dir, timeout, all git methods
def _make_tracker(analyzer, git_client)       # Constructs ProposalTracker with fixed UTC clock
```

Overrides follow the convention: plain values are wrapped in `Mock(return_value=v)`, pre-built `Mock` objects are assigned directly.

---

## 13. Move Detection

### Problem

When a proposal file is renamed across directories (e.g., DEP moving from `draft/0007.rst` to `accepted/0007.rst`), git reports this as a delete + add pair. Without handling, the delete handler marks the proposal as WITHDRAWN and the add handler creates a duplicate — producing a spurious WITHDRAWN notification and losing the status transition.

### Solution

Before processing changes, detect "moved" proposals by matching proposal numbers across delete and add operations:

```python
def _detect_moved_proposals(filtered, parser) -> set[str]:
    add_numbers = {parser.extract_number(p) for non-delete paths} - {""}
    moved = set()
    for delete_path in delete_paths:
        num = parser.extract_number(delete_path)
        if num and num in add_numbers:
            moved.add(num)
    return moved
```

Processing order: **adds first, then deletes** (skipping moved numbers). This ensures the add handler updates the existing proposal with the new status and file path, while the paired delete is silently dropped.

### Edge Cases

- **False positive**: If two *different* proposals with the same number are deleted and added in one commit, the delete is incorrectly skipped. This is extremely unlikely (requires a number collision) and the worst case is a missing WITHDRAWN notification — the final DB state remains correct.
- **RFC 2071**: This duplicate (redirect stub + real file) lives at rest, not during moves. Not affected.

---

## 14. Logging Requirements

### Levels

| Level | Purpose | Examples |
|---|---|---|
| `INFO` | Normal operation milestones | check start/complete, status changes, deletions, clone events |
| `DEBUG` | Detailed tracing | parsed proposals, moved proposal detection, unknown deletes, analysis completion |
| `WARNING` | Degraded but recoverable | parse failures, analysis failures, missing directories, unexpected return types |

### Required Log Points

**Tracker (`tracker.py`):**

| Event | Level | Fields |
|---|---|---|
| Check started | INFO | kind |
| Repo ready | INFO | kind, commit (short) |
| No new commits | INFO | kind |
| Incremental check | INFO | kind, changed count, filtered count, commit range |
| Initial check file scan | INFO | kind, parsed count, directory |
| Initial check completed | INFO | kind, total, verification number, duration |
| Proposal changed | INFO | kind, number, old→new status |
| Proposal deleted | INFO | kind, number, old→new status |
| Check completed | INFO | kind, report count, duration |
| Moved proposals detected | DEBUG | kind, numbers |
| Skipping moved delete | DEBUG | kind, number |
| Unparseable file in initial check | DEBUG | path, error |
| Unknown proposal deleted | DEBUG | kind, path |
| Tracker state created | INFO | kind |
| Repo cloned | INFO | url, sanitized name |
| Parse failure (incremental) | WARNING | path, error |
| Parse failure (verification pick) | WARNING | kind, path |
| Initial check dir not found | WARNING | kind, directory |
| Initial check no files | WARNING | kind |
| Check failed (per-kind) | WARNING | kind, error |

**Parser (`parser.py`):**

| Event | Level | Fields |
|---|---|---|
| File parsed | DEBUG | parser type, file path, number, raw_status |
| Encoding fallback | DEBUG | file path |

**Analysis (`analysis.py`):**

| Event | Level | Fields |
|---|---|---|
| Analysis completed | DEBUG | kind, number |
| Analysis unexpected return type | WARNING | kind, number, type name |
| Analysis failed | WARNING | kind, number, error |

### Log Format

All log messages use `%s` formatting (not f-strings) for lazy evaluation. Commit hashes are truncated to 12 characters in log output for readability. Durations are reported in seconds with one decimal place.
