# Safe `.git` Suffix Stripping - Design Document

## Problem Statement

The code uses `rstrip(GIT_SUFFIX)` in multiple places to remove `.git` suffixes from repository URLs. However, `rstrip()` removes **all** occurrences of **any** character in the string `".git"` from the right side, not just the literal suffix `.git`.

### Bug Examples

```python
"OpenList".rstrip(".git")  # Returns "OpenLis" (removes 't')
"vue.js".rstrip(".git")    # Returns "vue"   (removes '.js')
"mygit".rstrip(".git")     # Returns "my"    (removes 'git')
"test.git".rstrip(".git")  # Returns "test"  (correct)
```

### Current Impact

When processing `OpenListTeam/OpenList`, the `_parse_owner_repo()` function in `src/progress/github.py:130` incorrectly strips the trailing 't', resulting in `OpenListTeam/OpenLis`.

## Solution Design

### Core Approach

Create a utility function `strip_git_suffix()` in `src/progress/utils.py` that safely removes only the exact `.git` suffix, then replace all `rstrip(GIT_SUFFIX)` calls throughout the codebase.

### Implementation Details

#### New Utility Function

**Location:** `src/progress/utils.py`

```python
def strip_git_suffix(name: str) -> str:
    """Safely remove .git suffix from a string.

    Unlike str.rstrip('.git'), this only removes the exact suffix.

    Args:
        name: String that may end with .git

    Returns:
        String with .git suffix removed if present

    Examples:
        >>> strip_git_suffix("owner/repo.git")
        'owner/repo'
        >>> strip_git_suffix("OpenList")
        'OpenList'
        >>> strip_git_suffix("vue.js")
        'vue.js'
    """
    if name.endswith(".git"):
        return name[:-4]
    return name
```

#### Locations to Update

1. **`src/progress/github.py:130`** - `_parse_owner_repo()` function
   ```python
   # Before:
   return parts[0], parts[1].rstrip(GIT_SUFFIX)

   # After:
   from .utils import strip_git_suffix
   return parts[0], strip_git_suffix(parts[1])
   ```

2. Search for any other occurrences of `rstrip(GIT_SUFFIX)` in the codebase

### Testing Strategy

#### Unit Tests

Add comprehensive test cases to `tests/test_utils.py`:

```python
@pytest.mark.parametrize(
    "input_name,expected",
    [
        # Basic .git suffix removal
        ("owner/repo.git", "owner/repo"),
        ("repo.git", "repo"),
        # Names ending with characters from .git set
        ("OpenList", "OpenList"),      # Ends with 't'
        ("vue.js", "vue.js"),          # Contains '.' and ends with 's'
        ("mygit", "mygit"),            # Ends with 'git'
        ("test.g", "test.g"),          # Ends with 'g'
        ("test.i", "test.i"),          # Ends with 'i'
        ("test.t", "test.t"),          # Ends with 't'
        # Edge cases
        ("", ""),
        ("git", "git"),
        (".git", ""),
        ("a.git", "a"),
    ],
)
def test_strip_git_suffix(input_name, expected):
    from progress.utils import strip_git_suffix
    assert strip_git_suffix(input_name) == expected
```

#### Integration Tests

Verify repository URL parsing works correctly:
- `OpenListTeam/OpenList` → `OpenListTeam/OpenList`
- `OpenListTeam/OpenList.git` → `OpenListTeam/OpenList`
- `https://github.com/OpenListTeam/OpenList.git` → `OpenListTeam/OpenList`
- `git@github.com:OpenListTeam/OpenList.git` → `OpenListTeam/OpenList`

### Error Handling

The function handles edge cases gracefully:
- Strings shorter than 4 characters → returned as-is
- Strings not ending with `.git` → returned as-is
- Empty strings → returned as-is
- Exact match `.git` → returns empty string

### Migration Path

1. Add `strip_git_suffix()` to `utils.py`
2. Add comprehensive unit tests
3. Update `github.py` to use the new function
4. Run all existing tests to ensure no regressions
5. Verify the fix with the specific `OpenListTeam/OpenList` case

## Success Criteria

- ✅ `OpenListTeam/OpenList` is correctly parsed (not truncated to `OpenLis`)
- ✅ All existing tests pass
- ✅ New test cases cover the bug scenarios
- ✅ No other `rstrip(GIT_SUFFIX)` occurrences remain in the codebase
