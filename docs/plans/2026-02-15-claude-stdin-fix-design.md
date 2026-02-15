# Claude CLI stdin Fix Design

## Problem

Production deployment fails with error:

```
2026-02-15 17:01:54,469 [ERROR] [MainProcess] [repo_checker_2] - Claude Code release analysis failed: [Errno 7] Argument list too long: 'claude'
```

## Root Cause

Three methods in `src/progress/ai/analyzers/claude_code.py` pass the prompt as a CLI argument to `claude -p <prompt>`:

1. `_run_claude_release_analysis` (line 374-378)
2. `_run_claude_readme_analysis` (line 273-277)
3. `generate_title_and_summary` (line 439-443)

When prompts contain large content (release notes with diff, README content, aggregated reports), the total argument length can exceed the OS `ARG_MAX` limit (~2MB on Linux), causing the `[Errno 7] Argument list too long` error.

## Solution

Pass the prompt via stdin using the `input` parameter of `run_command`, matching the pattern already used in `_run_claude_analysis` and `_run_claude_text_analysis`.

## Implementation

### Changes to `src/progress/ai/analyzers/claude_code.py`

**Method: `_run_claude_release_analysis`**

```python
# Before (line 374-378)
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
)

# After
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
)
```

**Method: `_run_claude_readme_analysis`**

```python
# Before (line 273-277)
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
)

# After
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
)
```

**Method: `generate_title_and_summary`**

```python
# Before (line 439-443)
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
).strip()

# After
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
).strip()
```

## Testing

Existing tests should continue to pass since the behavior is functionally identical. The change only affects how data is passed to the subprocess, not the actual processing logic.

## Risk Assessment

**Low Risk**: This is a straightforward refactor that uses an existing, proven pattern in the codebase. The `run_command` function already supports stdin input, and `_run_claude_analysis` has been using this approach successfully.
