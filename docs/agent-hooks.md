# AI Agent Hooks

Project-local lifecycle hooks for Claude Code, Codex, ZCode, Trae, and OpenCode
that keep the code the agents write clean, and refuse to let an agent finish
while `ruff check` fails.

Most agents share the hook scripts in `.claude/hooks/` as a single source —
only the command string differs per agent (Claude/Trae inject a project-dir
env var). Trae additionally reads `.claude/settings.json` natively, so no
separate `.trae/hooks.json` is needed (and would cause each hook to run twice
via merge). **Codex and ZCode are the exceptions**: Codex edits files through
a single freeform `apply_patch` tool (not Claude-style `Edit`/`Write`), and
ZCode's runtime ignores workspace-scope hook configs — each ships independent
scripts tailored to its own hook contract (see the Codex and ZCode sections
below).

| Agent | Hooks config | Scripts |
|-------|--------------|---------|
| Claude Code | `.claude/settings.json` | `.claude/hooks/post_tool_use.py`, `.claude/hooks/stop.py` |
| Codex | `.codex/hooks.json` | `.codex/hooks/post_tool_use.py`, `.codex/hooks/stop.py` |
| ZCode | `~/.zcode/cli/config.json` | `.zcode/hooks/post_tool_use.py`, `.zcode/hooks/stop.py` |
| Trae | reads `.claude/settings.json` natively | (same `.claude/hooks/` scripts) |
| OpenCode | `.opencode/plugins/hooks.ts` (auto-loaded) | (self-contained; no shared scripts) |

## OpenCode — `.opencode/plugins/hooks.ts`

OpenCode has no declarative hooks system; its Plugin SDK is the only way to
intercept tool execution and session lifecycle. The plugin is **auto-loaded**
from `.opencode/plugins/` (no `opencode.json` registration needed) and is
self-contained — it runs `ruff` directly via Bun's shell API instead of
delegating to any Python script.

OpenCode already ships a built-in Format service that runs `ruff format`
(by extension) after every `write`/`edit`/`apply_patch`, so the plugin does
**not** re-implement formatting. It closes the two gaps the built-in leaves
open:

- **`tool.execute.after` — per-file `ruff check --fix`.** After every
  `write`/`edit`/`apply_patch` it extracts the edited path(s) — for
  `apply_patch`, by parsing the patch text the same way the built-in does
  (`*** Update File:` / `*** Add File:` headers, `*** Move to:` resolved to the
  destination) — and runs `ruff format` + `ruff check --fix` on each `.py`/`.pyi`
  file via a `switch` on the extension (other extensions are no-ops today, new
  cases drop in later). It is silent and idempotent: `.quiet().nothrow()` means
  a ruff failure never blocks the agent.

- **`event` (`session.idle`) + `chat.message` — session-end lint gate.**
  OpenCode's event hooks are fire-and-forget and cannot return a
  `{"decision":"block"}` the way Claude's Stop hook can. Instead, on the first
  `session.idle` of each real user turn the hook re-runs `ruff check --fix`
  across `src/`; if residual errors remain that ruff cannot auto-fix, it injects
  a synthetic user message via `client.session.prompt()` so the agent keeps
  working. This mirrors Claude's `stop_hook_active`: at most **one** feedback
  per real user prompt — subsequent idles in the same turn stand down, and a
  fresh non-synthetic user message resets the gate. The one-turn-only latch is
  a module-level `Map<sessionID, { feedbackGiven }>`; OpenCode plugins are
  stateful (the module is imported once and the hook object lives for the
  instance lifetime), so it persists across events within a process.

## Codex — `.codex/hooks/`

Codex has its own hook scripts under `.codex/hooks/`, separate from
`.claude/hooks/`. The split is deliberate: Codex edits files through one
freeform `apply_patch` tool (not Claude-style `Edit`/`Write`), and its hook
contract differs in ways that matter.

- **`post_tool_use.py`** (PostToolUse, matcher `apply_patch`): reads the edited
  paths out of the V4A patch text carried in `tool_input.command` (Codex
  supplies no `file_path` field — the paths live inside the patch). Only
  `*** Update File:` and `*** Add File:` paths are formatted; `*** Delete File:`
  is skipped (the file no longer exists), and `*** Update File:` followed by
  `*** Move to:` is treated as a rename — the hook formats the *destination*
  path (the source has been removed). Each `.py`/`.pyi` path gets
  `ruff format` then `ruff check --fix`. The hook never blocks: it is a silent
  best-effort fixer (exit 0), and any ruff failure it cannot auto-fix is
  surfaced as a stderr warning while the turn continues.

- **`stop.py`** (Stop): runs a repo-wide `ruff check --fix` when the agent
  wants to finish. If residual unfixable lint remains it prints
  `{"decision":"block","reason":"..."}` (exit 0), and the reason is fed back to
  the agent as a continuation prompt. The only loop guard is the
  `stop_hook_active` flag set on the second Stop invocation: when it is
  truthy the hook stands down and lets the agent stop, leaving the final lint
  verdict to CI.

## ZCode — `.zcode/hooks/`

ZCode ships its own hook scripts under `.zcode/hooks/`. Like Codex, the split
is deliberate: ZCode's `Write`/`Edit` tools expose the edited path as a
structured `file_path` field (not V4A patch text), and its hook stdin uses
camelCase keys (`toolInput`, `stopHookActive`). Unlike every other agent here,
the hook config cannot live in the repository at all: the ZCode agent runtime
(v2.1.0) **strips workspace-scope hooks** from `.zcode/config.json` with a
"Project hooks were ignored by the security policy" warning, so the config
must live in the user-level `~/.zcode/cli/config.json`. Because that file
applies to every workspace, the command strings guard on the existence of
`.zcode/hooks/` (via `${ZCODE_PROJECT_DIR}`) and silently exit 0 elsewhere.
See `.zcode/README.md` for the evidence and details.

- **`post_tool_use.py`** (PostToolUse, matcher `Edit|Write`): reads
  `toolInput.file_path` and runs `ruff check --fix` then `ruff format` on the
  edited `.py`/`.pyi` file. Never blocks; ruff failures surface as stderr
  warnings.

- **`stop.py`** (Stop): identical semantics to the shared stop script, with
  the loop guard reading the camelCase `stopHookActive` flag. ZCode natively
  caps Stop continuations at three.

## PostToolUse — `post_tool_use.py`

Fires after every `Edit`/`Write`. Reads `tool_input.file_path` directly
(Claude Code’s `Edit`/`Write` tools provide the path as a structured field,
unlike Codex’s `apply_patch` which embeds paths inside V4A patch text). For
`.py`/`.pyi` files it runs `ruff check --fix` then `ruff format`, reading the
project’s own `[tool.ruff]` config (no hard-coded rule set, so it stays
in sync with CI). It **never blocks** the agent - formatting is best-effort.
A genuine ruff failure is surfaced as a stderr warning and the turn
continues; the real gate is the Stop hook.

## Stop — `stop.py`

Fires when the agent wants to end the turn. It runs a full `uv run ruff check --fix`:

- **Lint clean** → exit 0, no output. The agent stops normally.
- **Lint dirty** → exit 0, printing `{"decision":"block","reason":"..."}` to
  stdout. The agent is sent back for another pass with the ruff output as a
  continuation prompt.

### Why exit 0 + JSON, not exit 2

Both agents document exit-0-plus-JSON as the canonical blocking mechanism.
Claude's reference states it plainly: *"Instead of exiting with code 2 to
block, exit 0 and print a JSON object to stdout."* Exit 2 treats the feedback
as a hard error and discards stdout; the JSON form is structured, neutral, and
lets `reason` carry the exact diagnostics back to the agent.

### Infinite-loop guard

If the agent fixes the wrong thing the Stop hook would fire again, block again,
and the turn would never end. The hook input carries `stop_hook_active`
(boolean) — it is `false` on the first Stop and `true` on every subsequent one
within the same turn. When it is `true` the hook **stands down** and lets the
agent stop. The authoritative lint verdict then belongs to CI, never to a hook
loop.

| `stop_hook_active` | ruff result | Hook action |
|--------------------|-------------|-------------|
| `false` | clean | pass (exit 0, no output) |
| `false` | dirty | block (exit 0 + `{"decision":"block",...}`) |
| `true` | (any) | pass — let the agent stop |

## Testing the hooks locally

```bash
# format hook on a clean file: no output, exit 0
echo '{"tool_name":"Edit","tool_input":{"file_path":"src/progress/__init__.py"}}' \
  | uv run .claude/hooks/post_tool_use.py

# stop hook, clean tree: no output, exit 0
echo '{"hook_event_name":"Stop","stop_hook_active":false}' \
  | uv run .claude/hooks/stop.py

# stop hook, infinite-loop guard active: no output, exit 0
echo '{"hook_event_name":"Stop","stop_hook_active":true}' \
  | uv run .claude/hooks/stop.py
```

To see the block path, temporarily introduce a lint error (e.g. an unused
import) and re-run the Stop hook — it prints the `{"decision":"block",...}`
JSON with the ruff diagnostics in `reason`.
