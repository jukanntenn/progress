import { isAbsolute, relative, resolve as pathResolve } from "node:path"
import type { Plugin } from "@opencode-ai/plugin"

/**
 * OpenCode plugin: delegate formatting + session-end lint gate to prek.
 *
 * `prek.toml` is the single source of truth for what gets formatted vs linted
 * (the `format` and `lint` hook groups). After every write/edit/apply_patch
 * this runs `prek run --group format --group lint --files <paths>` so the
 * edited file is left canonical (format + lint-fix). On the first
 * `session.idle` of each real user turn it runs `prek run --group lint
 * --all-files`; if residual lint remains it injects a synthetic user message
 * (OpenCode events are fire-and-forget — they cannot return a block decision).
 * The latch mirrors the Claude/ZCode `stop_hook_active` guard: at most ONE
 * feedback per real user prompt. Generated files are exempted in `prek.toml`,
 * so prek never touches them.
 *
 * The prek operations are shared with the Claude/Codex/ZCode hooks via
 * `.agents/hooks/_core.py`; OpenCode uses Bun's shell `$` directly instead.
 */

const PATCH_FILE_RE = /^\*\*\* (?:Update|Add) File: (.+)$/
const PATCH_MOVE_RE = / -> \*\*\* Move to: (.+)$/

// The desktop app launches the sidecar with cwd=$HOME, so anchor on the plugin
// file location (always inside the project) instead of the process cwd.
const PROJECT_ROOT = pathResolve(import.meta.dir, "../..")

// Per-session feedback gate. Resets on a real (non-synthetic) user message,
// sets after the first idle-time feedback. Keyed by sessionID.
const turnState = new Map<string, { feedbackGiven: boolean }>()

function toRepoRel(p: string): string {
  const abs = isAbsolute(p) ? p : pathResolve(PROJECT_ROOT, p)
  return relative(PROJECT_ROOT, abs)
}

function extractPaths(filePath: string | undefined, patchText: string | undefined): string[] {
  if (filePath) return [filePath]
  if (!patchText) return []
  const paths: string[] = []
  for (const line of patchText.split("\n")) {
    const m = line.match(PATCH_FILE_RE)
    if (!m) continue
    const move = m[1].match(PATCH_MOVE_RE)
    paths.push((move ? move[1] : m[1]).trim())
  }
  return paths
}

export const HooksPlugin: Plugin = async ({ $, client }) => {
  return {
    "chat.message": async (_input, output) => {
      const parts = output.parts as Array<{ synthetic?: boolean }>
      if (parts.length > 0 && parts.every((p) => p.synthetic)) return
      turnState.set(output.message.sessionID, { feedbackGiven: false })
    },

    "tool.execute.after": async (input) => {
      if (input.tool !== "write" && input.tool !== "edit" && input.tool !== "apply_patch") return
      const args = (input.args ?? {}) as { filePath?: string; patchText?: string }
      const rels = extractPaths(args.filePath, args.patchText).map(toRepoRel).filter(Boolean)
      if (rels.length === 0) return
      await $`prek run -C ${PROJECT_ROOT} --group format --group lint --files ${rels}`
        .quiet()
        .nothrow()
    },

    event: async ({ event }) => {
      if (event.type !== "session.idle") return
      const sessionID = (event.properties as { sessionID?: string } | undefined)?.sessionID
      if (!sessionID) return

      const state = turnState.get(sessionID) ?? { feedbackGiven: false }
      if (state.feedbackGiven) return

      const gate = await $`prek run -C ${PROJECT_ROOT} --group lint --all-files`.quiet().nothrow()
      if (gate.exitCode === 0) return

      state.feedbackGiven = true
      turnState.set(sessionID, state)

      const output = (gate.stdout.toString("utf8") + gate.stderr.toString("utf8")).trim()

      await client.session
        .prompt({
          path: { id: sessionID },
          body: {
            parts: [
              {
                type: "text",
                synthetic: true,
                text: [
                  `prek lint could not auto-fix all issues; residual lint remains.`,
                  ``,
                  `Diagnostics:`,
                  output,
                  ``,
                  `Requirements:`,
                  `1. Fix ALL of the errors above — do not stop after fixing just one.`,
                  `2. Before declaring the task complete, self-verify by re-running: \`prek run --group lint --all-files\`.`,
                  `3. Only consider the task done when that command exits cleanly with exit code 0.`,
                  `Do not end your turn until the check passes.`,
                ].join("\n"),
              },
            ],
          },
        })
        .catch(() => {})
    },
  }
}
