# AI Agent Hooks

English | [中文](agent-hooks.zh.md)

Project-local lifecycle hooks for Claude Code, Codex, ZCode, and OpenCode that keep the code the agents write clean, and refuse to let an agent finish while lint fails.

## Design: prek is the single source of truth

Every hook delegates formatting and linting to **prek** (the project's pre-commit runner). prek runs in **workspace mode**: the root `prek.toml` holds the backend + builtin hooks, and `web/prek.toml` holds the frontend (eslint/prettier) hooks. Both files define the same two group names:

- **`format`** — byte-mutating formatters that never fail: `ruff-format`, `prettier`, `trailing-whitespace`, `end-of-file-fixer`, `mixed-line-ending`.
- **`lint`** — linters that can fail (and `--fix` what they can): `ruff-check`, `eslint`.

The agent-agnostic operations live in **`.agents/hooks/_core.py`**, which just runs prek:

```python
format(paths)            # prek run --group format --files <paths>          (best-effort)
lint(*paths, all_files=) # prek run --group lint   --files <paths> | --all-files
```

The function names mirror the group names 1:1. prek's own per-hook `files` filters and workspace directory routing send each file to the right tool (a `.py` path only hits ruff in the root project; a `.ts` path only hits eslint/prettier in the web/ project), so the agent shells never encode an extension→tool mapping — that mapping lives only in the two `prek.toml` files. Adding a new formatter is a one-line config change; every agent picks it up automatically.

## Shells vs core

Each agent keeps its **own hook shell** (payload parsing + stdout protocol differ per agent — they are NOT unified), and the shells share **only** the prek operations via `_core`:

| Agent | Hooks config | Shell | Payload / protocol |
|-------|--------------|-------|--------------------|
| Claude Code | `.claude/settings.json` | `.claude/hooks/post_tool_use.py`, `stop.py` | `tool_input.file_path`; snake_case; block = `{"decision":"block","reason":...}` |
| Codex | `.codex/hooks.json` | `.codex/hooks/post_tool_use.py`, `stop.py` | `apply_patch` V4A patch text in `tool_input.command`; `stop_hook_active` guard |
| ZCode | `~/.zcode/cli/config.json` (user-level) | `.zcode/hooks/post_tool_use.py`, `stop.py` | `toolInput.file_path`; camelCase; `stopHookActive`; caps at 3 continuations |
| OpenCode | `.opencode/plugins/hooks.ts` (auto-loaded) | (self-contained TS) | `args.filePath`/`patchText`; OpenCode events can't block, so it injects a synthetic message |

OpenCode runs under Bun, so its shell calls `prek run -C <root> --group ...` directly via Bun's shell `` $ `` instead of importing `_core` — but it uses the exact same groups and semantics.

## PostToolUse — per-file format

Fires after every edit. The shell extracts the edited path(s) and runs `_core.format(paths)` then `_core.lint(*paths)` (both best-effort, exit code ignored). After the call the file is fully canonical — formatted **and** lint-fixed (e.g. unused imports removed) — so a later `prek run` on it is a no-op. This is why an agent edit followed by `prek` leaves the tree clean: the agent runs the same prek groups prek itself will run.

## Stop — repo-wide lint gate

Fires when the agent wants to end the turn. The shell runs `_core.lint(all_files=True)` (`prek run --group lint --all-files`):

- **Lint clean** → exit 0, no output. The agent stops normally.
- **Lint dirty** → the shell prints the agent's block form (Claude/Codex/ZCode: `{"decision":"block","reason":...}` JSON with prek's output; OpenCode: a synthetic user message). The agent is sent back for another pass.

prek treats "a fixer modified a file" as nonzero too (re-stage semantics). In a CI-gated clean tree nothing modifies at Stop — the edited files were already fixed by PostToolUse — so nonzero cleanly means unfixable lint remains.

### Infinite-loop guard

The hook input carries a "stop already active" flag (`stop_hook_active` / `stopHookActive`) — `false` on the first Stop, `true` thereafter. When truthy the hook stands down and lets the agent stop; the authoritative lint verdict then belongs to CI, never to a hook loop.

## Generated files are exempt

Generated artifacts (`progress.pot`, `web/openapi.json`, `web/src/api/schema.ts`) are kept verbatim — their bytes are owned by their generator, not by any hook (see the project's drift conventions). They are excluded in two complementary places:

- **The prek `exclude`** — the root `prek.toml` lists all of them (it is the workspace-root config, so its exclude is applied globally before files reach any project's hooks, including the root builtin hooks), and `web/prek.toml` repeats the two web/ artifacts for the `cd web && prek run` case. So no prek hook (format, lint, builtin) touches them, and the `_core` format/lint calls skip them automatically.
- **`web/.prettierignore`** (`openapi.json`, `src/api/schema.ts`) and the eslint `ignores` — so `pnpm format` / `pnpm lint` (direct dev invocations, not via prek) skip them too.

`web/pnpm-lock.yaml` and the `.po` catalogs (hand-translated) are the tracked exceptions: lockfiles are ignored via `.prettierignore`, and `.po` stays in scope for its hygiene + catalog-lint hooks.

## ZCode config is user-level

The ZCode runtime (v2.1.0, WSL) strips workspace-scope hooks from `.zcode/config.json` ("Project hooks were ignored by the security policy"). The hook config therefore lives in the **user-level** `~/.zcode/cli/config.json` and guards on the existence of `.zcode/hooks/` via `${ZCODE_PROJECT_DIR}` so other workspaces are unaffected. See `.zcode/README.md` for the evidence.

## Testing the hooks locally

```bash
# PostToolUse on a clean file: no output, exit 0
echo '{"tool_input":{"file_path":"src/progress/__init__.py"}}' \
  | uv run .claude/hooks/post_tool_use.py

# Codex PostToolUse (V4A patch text carries the path)
printf '%s' '{"tool_input":{"command":"*** Update File: src/progress/__init__.py\nprint(1)"}}' \
  | uv run .codex/hooks/post_tool_use.py

# Stop gate, loop guard active: no output, exit 0
echo '{"stop_hook_active":true}' | uv run .claude/hooks/stop.py

# Functional: an ill-formatted temp file IS reformatted by the hook
printf 'x=1\n' > /tmp/_t.py  # (place inside the repo for prek to see it)
echo '{"tool_input":{"file_path":"_t.py"}}' | uv run .claude/hooks/post_tool_use.py
```

To see the block path, introduce a lint error (e.g. an unused import) and run the Stop hook — it prints the `{"decision":"block",...}` JSON with the prek diagnostics in `reason`.
