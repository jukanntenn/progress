# Storage Framework Refactor Design

**Date:** 2025-02-13
**Status:** Approved
**Type:** Refactoring

## Overview

Refactor report persistence layer to use protocol-based storage framework while preserving all existing functionality and maintaining zero changes to Peewee models.

## Goals

- **Multi-backend flexibility** - Support different storage backends (filesystem, database, API) beyond just SQLite
- **Clean architecture** - Protocol-based abstraction with better separation of concerns
- **Testing & maintainability** - Better testability and reduced coupling in the storage layer
- **Preserve everything** - All existing features work exactly the same way, only architecture changes

## Architecture

### Core Components

1. **Storage Protocol Interface** - `Storage` protocol defines `save(title: str, body: str) -> str` contract
2. **Backend Implementations** - FileStorage, DBStorage, MarkpostStorage, AutoStorage
3. **Composite Decorator** - `CombinedStorage` wraps any primary storage, saves to existing `Report` model first (with all existing fields: repository_id, current_commit, previous_commit, markpost_url, content), then delegates to primary backend
4. **Factory Function** - `get_storage()` returns configured storage instance based on config
5. **Drop-in Replacement** - Replaces `db.save_report()` with `get_storage().save()`, same signature

### What Stays Exactly the Same (Zero Modifications)

- **ALL** Peewee models in `src/progress/models.py` - no schema changes, no field changes
- Report generation logic and templates
- CLI interface and command flow
- Markpost client and notification system
- Configuration structure (only adding `report.storage` enum)
- All foreign key relationships and constraints

### What Changes

- Report saving logic moved from `db.save_report()` to storage framework
- Storage backend configurable via `config.report.storage` enum
- Where markdown content gets stored (database, filesystem, or Markpost) - Report model content field always populated for history

## Component Structure

```
src/progress/storages/
├── __init__.py           # Factory function get_storage()
├── base.py               # Storage protocol interface
├── file.py               # Filesystem storage backend
├── db.py                 # Database storage backend (uses existing Report model)
├── markpost.py           # Markpost API storage backend
├── combined.py           # Composite decorator (saves to Report + primary backend)
└── auto.py               # Auto-fallback storage (Markpost if configured, else file)

tests/storage/
├── test_base.py          # Protocol compliance tests
├── test_file.py          # FileStorage tests
├── test_db.py            # DBStorage tests
├── test_markpost.py      # MarkpostStorage tests
├── test_combined.py      # CombinedStorage tests
└── test_auto.py          # AutoStorage tests
```

### Component Responsibilities

- **`base.py`**: `Storage` protocol with single `save(title, body) -> str` method
- **`db.py`**: Wraps existing `Report.create()` from `models.py`, returns report ID
- **`file.py`**: Saves markdown to `data/reports/{timestamp}.md`, creates directory if needed
- **`markpost.py`**: Wraps existing `MarkpostClient.upload()`, returns URL
- **`combined.py`**: Decorator that calls `db.save()` first (populates Report model), then delegates to primary backend
- **`auto.py`**: Lazy initialization - checks `config.markpost.base_url`, returns MarkpostStorage or FileStorage
- **`__init__.py`**: `get_storage()` factory function reads `config.report.storage` enum, returns appropriate storage instance

## Data Flow

### Current Report Saving Flow

```
CLI check command → Analyze changes → Generate report via Jinja2 → db.save_report(repository, commits, content, markpost_url) → Report model
```

### New Report Saving Flow

```
CLI check command → Analyze changes → Generate report via Jinja2 → get_storage().save(title, body) → CombinedStorage
                                                                                                                                                   ↓
                                                                                                                                            saves to Report model (metadata)
                                                                                                                                                   ↓
                                                                                                                                            delegates to primary backend (content)
```

### Detailed Flow with CombinedStorage

1. **Caller generates report** → `markdown_content = template.render(...)`
2. **Caller saves report** → `storage.save(title="Repository Report", body=markdown_content)`
3. **Factory returns storage** → `CombinedStorage(MarkpostStorage(client))` or similar
4. **CombinedStorage.save() executes:**
   - Step 1: `Report.create(repository_id=..., current_commit=..., previous_commit=..., content=body, markpost_url=None)` → saves metadata to database
   - Step 2: `primary_backend.save(title, body)` → saves content to primary backend
   - Step 3: If primary is Markpost, update `Report.markpost_url` with returned URL
   - Step 4: Return primary backend result (file path, URL, or ID)

## Error Handling

- Backends raise descriptive `FeeberException` with context (what failed, why, location)
- Database save always attempted before primary backend (for tracking)
- If primary backend fails, database record still exists (audit trail)
- Exceptions bubble up through protocol; CLI handles/logging as appropriate

## Configuration

### Add to config.py

```python
class StorageType(str, Enum):
    DB = "db"
    FILE = "file"
    MARKPOST = "markpost"
    AUTO = "auto"

class ReportConfig(BaseSettings):
    storage: StorageType = StorageType.AUTO
```

### config.toml

```toml
[report]
storage = "auto"  # or "db", "file", "markpost"
```

### Storage Type Behavior

- `DB`: Database only (no external storage)
- `FILE`: Filesystem + database tracking (via CombinedStorage)
- `MARKPOST`: Web service + database tracking (via CombinedStorage)
- `AUTO`: Markpost if configured, otherwise filesystem (via CombinedStorage)

## Testing Strategy

### Streamlined TDD Approach

**Test structure mirrors source:**
- `test_base.py` - 1 test: protocol compliance
- `test_file.py` - 3 tests: happy path, directory creation, permission error
- `test_db.py` - 1 test: mocks Report.create(), verifies delegation
- `test_markpost.py` - 1 test: mocks MarkpostClient, verifies upload call
- `test_combined.py` - 2 tests: saves to db + primary, returns primary result
- `test_auto.py` - 2 tests: markpost when configured, file fallback

**Total: 10 focused tests**

### Testing Priorities

1. **Protocol compliance** - Verify any class with `save()` method works as Storage
2. **Backend behavior** - Mock external dependencies (Report model, MarkpostClient), verify `save()` calls correct methods with correct arguments
3. **Composite pattern** - Verify CombinedStorage calls both db and primary backends in right order, returns primary result
4. **Factory logic** - Mock config, verify correct backend instantiation based on storage_type enum
5. **Error handling** - Verify descriptive exceptions raised with context

### Testing Tools

- `pytest` (existing dependency)
- `unittest.mock.Mock` (standard library)
- `tmp_path` fixture for filesystem tests
- **No new dependencies**

### Verification

- Run `pytest tests/storage/` after each component commit
- Quick smoke test: `pytest tests/storage/ -v -q`
- Type checking: `mypy src/progress/storages/`
- Linting: `ruff check src/progress/storages/`

## Migration Approach

### Big Bang Replacement - Single PR with Atomic Commits

**Phase 1: Configuration setup (1 commit)**
- Add `StorageType` enum and `ReportConfig` to `config.py`
- Add default `storage = "auto"` to existing config files
- Tests: Verify config loads with new field, backward compatible

**Phase 2: Storage framework implementation (6 commits)**
1. Protocol + tests
2. FileStorage + tests
3. DBStorage + tests
4. MarkpostStorage + tests
5. CombinedStorage + tests
6. AutoStorage + tests

**Phase 3: Factory + integration (2 commits)**
7. Factory function + tests
8. All storage tests

**Phase 4: Drop-in replacement (1 commit)**
9. Modify `db.save_report()` to use `get_storage().save()`
10. Update `db.py` imports, add error handling

**Phase 5: Verification (1 commit)**
11. Run full test suite: `pytest tests/ -v`
12. Manual smoke test: `uv run progress check`

**Total: ~10 commits across 5 phases**

### Rollback Strategy

- Each phase is atomic and can be reverted independently
- If Phase 4 breaks existing functionality, revert to Phase 3 state
- Database schema unchanged, so no data migration needed
- Feature flag not needed (big bang = go/no-go decision)

### Data Safety

- Report model fields unchanged - no data loss possible
- CombinedStorage always saves to database (preserves history)
- File storage writes to new directory (`data/reports/`), no conflicts

## Integration Points

**Files to modify:**
- `src/progress/config.py` - Add `StorageType` enum and `ReportConfig`
- `src/progress/db.py` - Replace `save_report()` body to call `get_storage().save(title, body)`

**Files that remain unchanged:**
- `src/progress/models.py` - All Peewee models
- `src/progress/cli.py` - CLI interface (consumes db.save_report)
- `src/progress/reporter.py` - Report generation
- `src/progress/markpost.py` - Markpost client
- `src/progress/notification.py` - Notification system
- All template files

## Success Criteria

### Functional Requirements

- ✓ All existing features work exactly the same (no behavior changes)
- ✓ Report saving works with all storage backends (db, file, markpost, auto)
- ✓ Report model always populated with metadata (repository_id, commits, content, markpost_url)
- ✓ CLI commands produce identical output (check, report, track-proposals)
- ✓ Markpost uploads work, notification system unchanged
- ✓ All existing tests pass without modification

### Architectural Requirements

- ✓ Zero changes to Peewee models in `src/progress/models.py`
- ✓ Protocol-based storage interface (`typing.Protocol`)
- ✓ Factory pattern for storage instantiation
- ✓ Composite decorator pattern for database + primary backend
- ✓ Drop-in replacement for `db.save_report()` (same signature, error behavior)

### Quality Requirements

- ✓ All new code follows project standards (imports at top, self-documenting, type hints)
- ✓ Unit tests for all storage components (≥80% coverage)
- ✓ No new external dependencies
- ✓ Type checking passes (mypy)
- ✓ Linting passes (ruff)

### Testing Requirements

- ✓ 10 focused tests across 6 test files
- ✓ All tests pass before merge
- ✓ Manual verification: `uv run progress check` produces reports
- ✓ Database verification: Report model records created correctly

### Performance Requirements

- ✓ No performance regression in report generation
- ✓ File storage: creates directories efficiently, uses nanosecond timestamps
- ✓ Database storage: uses existing `Report.create()` (same performance)
- ✓ Markpost storage: wraps existing client (same performance)

### Maintainability Requirements

- ✓ Clean separation: storage code isolated in `src/progress/storages/`
- ✓ Easy to extend: new storage backend = implement protocol, add to factory
- ✓ Easy to test: all backends mockable, no real database required for unit tests
- ✓ Clear documentation: docstrings for public API, inline comments explain why

### Streamlined Approach Success

- ✓ Single PR with ~10 atomic commits
- ✓ Each commit tests pass individually
- ✓ No unnecessary abstractions or premature optimization
- ✓ Implementation timeline measured in hours, not days
