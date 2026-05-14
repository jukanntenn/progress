---
name: gestating
description: >
  Transform an Intent Brief into structured fa tasks with specs and execution plans.
  Use this skill whenever the user provides an Intent Brief, describes a new feature or
  change they want planned, asks to break down work into tasks, or says anything like
  "I want to build X" or "plan this feature" or "here's what I need" — even if they
  don't explicitly mention tasks or specs. Also use when the user pastes a requirements
  document, product brief, or design proposal and wants it turned into actionable work.
---

# Gestating

You receive an Intent Brief — a description of what someone wants to build or change — and produce a complete, ready-to-execute task structure.

What you produce: a set of tasks, each with a `spec.md` (what + why + how) and a `plan.md` (step-by-step execution recipe). Another agent with zero codebase context will follow these plans mechanically, so they must be exhaustive and self-contained. No design decisions should be left to the executor.

## The Process

### Step 1: Create the parent task

Read the Intent Brief and derive a short, descriptive slug — lowercase, hyphen-separated, alphanumeric only (e.g., `add-user-auth`, `refactor-payment-flow`, `fix-memory-leak`).

```bash
fa task create <slug>
```

Capture the task ID and directory path from the output. You'll need them for every subsequent step.

### Step 2: Dissect the Intent Brief

Go through the Intent Brief methodically, resolving every design decision. For each aspect — scope, constraints, edge cases, data models, API contracts, UI behavior, error handling, performance — choose the most reasonable solution following best practices.

If a question can be answered by exploring the codebase, explore the codebase instead of guessing. Specifically look at:

- **Existing patterns**: Find similar features already implemented. How do they structure their code, tests, configuration?
- **Data models and schemas**: What tables/collections exist? What ORM is used? Naming conventions?
- **Configuration files**: What config format? Where are environment variables defined?
- **Test patterns**: What test framework? How are tests organized? Fixtures, mocks, factories?
- **Naming conventions**: Functions, classes, files, directories — follow the established style.

Walk the full design tree. Every branch. When you skip a branch because "it's obvious," you create a gap that the executor — who has zero context — cannot fill.

### Step 3: Review analysis and decisions

Review the design decisions you've made — not the writing yet, just the thinking:

- Are there unstated assumptions? If you assumed something the Intent Brief didn't explicitly say, call it out and validate it.
- Do any decisions contradict each other? Trace through the full flow and check.
- Did you skip any branches of the design tree? Go back and walk them.
- Does the scope match what was asked? No scope creep, no scope missed.

If you find issues, go back to Step 2 and resolve them before continuing.

### Step 4: Write specs and plans

#### Assess complexity

Decide whether this is a single task or needs decomposition into subtasks. There's no hard threshold — use your judgment based on the nature of the work. A task is complex when it has multiple independent deliverables, spans different areas of the codebase, or would produce a plan so long that different sections could be verified independently.

#### Simple task: single spec + plan

Write `spec.md` in the task directory.

Then write `plan.md` in the same directory. The plan must be detailed enough that someone who has never seen this codebase could execute it without making a single design decision. Every step should contain:

- Exact file paths (verify they exist on the filesystem before writing them into the plan)
- Specific function/class/variable names to use
- Import statements needed
- The exact location in a file where changes go (after function X, before class Y, at line N)
- What to test after each step

#### Complex task: decompose into subtasks

1. Write `spec.md` in the parent task directory (full specification).

2. For each subtask, create it:

   ```bash
   fa task create <subtask-slug> --parent <parent-id>
   ```

   Subtask slugs should describe their scope (e.g., `add-user-model`, `create-auth-endpoints`, `build-login-ui`).

3. Write a `plan.md` in each subtask directory. Each subtask plan must:
   - Be fully self-contained — the executor won't read other subtask plans
   - Restate any critical context from the parent spec (don't just say "see parent spec.md")
   - Include a clear verification step at the end
   - Not depend on the executor knowing anything about sibling subtasks

4. If there are dependencies between subtasks, document them in the parent spec and in each subtask's plan.

### Step 5: Review written artifacts

Review what you've actually written — the spec.md and plan.md files — not the thinking behind them:

- Do specs and plans align? No contradictions between what spec says and what plan does?
- Are all requirements from the Intent Brief covered? Map each requirement to a plan step.
- Is every plan step actionable without context? Read each step as if you've never seen this codebase before.
- Are file paths correct? Verify by checking the filesystem — don't guess paths.
- Are subtask boundaries clean? No tight coupling, no missing handoffs between subtasks.

If you find issues, go back to Step 4 and fix them.

### Step 6: Return result

Output a JSON result:

```json
{
  "task_id": <parent-task-id>,
  "task_path": "<absolute-path-to-parent-task-directory>"
}
```

If subtasks were created:

```json
{
  "task_id": <parent-task-id>,
  "task_path": "<absolute-path-to-parent-task-directory>",
  "subtasks": [
    {"task_id": <id>, "task_path": "<path>", "slug": "<slug>"},
    ...
  ]
}
```

## Writing guidelines

- Write in English.
- Specs describe what and why. Plans describe how, step by step.
- Plans are recipes, not essays. Every step is an action, not a concept.
- When you're tempted to write "implement the standard pattern," stop — write out the actual standard pattern.
- When you're tempted to write "handle edge cases," stop — list every edge case and what to do for each one.
- File paths in plans must be verified against the actual filesystem. Don't invent paths.
- If the Intent Brief is ambiguous, resolve the ambiguity using best practices and codebase conventions rather than asking the user. Document your resolution in the spec.
