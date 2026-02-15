# Claude CLI stdin Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the "Argument list too long" error by passing prompts to Claude CLI via stdin instead of CLI arguments.

**Architecture:** Three methods in `claude_code.py` currently pass prompts as CLI arguments. We will refactor them to use stdin via the `input` parameter of `run_command`, matching the existing pattern in `_run_claude_analysis` and `_run_claude_text_analysis`.

**Tech Stack:** Python 3.12+, subprocess (via existing `run_command` utility)

---

### Task 1: Fix `_run_claude_readme_analysis` method

**Files:**
- Modify: `src/progress/ai/analyzers/claude_code.py:273-277`

**Step 1: Modify the method to use stdin**

Change line 273-277 from:

```python
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
)
```

To:

```python
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
)
```

**Step 2: Run tests to verify**

Run: `uv run pytest tests/ai/ -v -k readme`
Expected: PASS (existing tests should continue to work)

**Step 3: Commit**

```bash
git add src/progress/ai/analyzers/claude_code.py
git commit -m "fix(ai): pass prompt via stdin in _run_claude_readme_analysis"
```

---

### Task 2: Fix `_run_claude_release_analysis` method

**Files:**
- Modify: `src/progress/ai/analyzers/claude_code.py:374-378`

**Step 1: Modify the method to use stdin**

Change line 374-378 from:

```python
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
)
```

To:

```python
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
)
```

**Step 2: Run tests to verify**

Run: `uv run pytest tests/ai/ -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/progress/ai/analyzers/claude_code.py
git commit -m "fix(ai): pass prompt via stdin in _run_claude_release_analysis"
```

---

### Task 3: Fix `generate_title_and_summary` method

**Files:**
- Modify: `src/progress/ai/analyzers/claude_code.py:439-443`

**Step 1: Modify the method to use stdin**

Change line 439-443 from:

```python
output = run_command(
    [self.claude_code_path, "-p", prompt],
    timeout=self.timeout,
    check=False,
).strip()
```

To:

```python
output = run_command(
    [self.claude_code_path, "-p"],
    input=prompt,
    timeout=self.timeout,
    check=False,
).strip()
```

**Step 2: Run full test suite**

Run: `uv run pytest -v`
Expected: PASS

**Step 3: Commit**

```bash
git add src/progress/ai/analyzers/claude_code.py
git commit -m "fix(ai): pass prompt via stdin in generate_title_and_summary"
```

---

### Task 4: Final verification

**Step 1: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests PASS

**Step 2: Verify the changes**

Run: `git diff HEAD~3 --stat`
Expected: Only `src/progress/ai/analyzers/claude_code.py` modified with 3 lines changed

**Step 3: Push or finalize**

The fix is complete. Deploy to production to verify the issue is resolved.
