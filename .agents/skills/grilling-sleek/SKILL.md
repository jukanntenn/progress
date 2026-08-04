---
name: grilling-sleek
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

Interview me relentlessly about every aspect of this until we reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask about one branch at a time, waiting for my feedback on each branch before continuing. Asking about several branches at once is bewildering.

If a *fact* can be found by exploring the environment (filesystem, tools, etc.), look it up rather than asking me. The *decisions*, though, are mine — put each one to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## How this skill works

You grill me through a web UI: each batch of questions becomes one web page I review and submit. This directory is self-contained — it bundles the CLI (`grill.js`) and the JSON schemas the CLI validates against. Locate this directory at runtime (the directory containing this `SKILL.md`) before invoking the CLI.

**One decision-tree branch per round.** Each batch's `questions[]` covers the sub-decisions of *one* branch. Resolve that branch from my answers, then push the next branch's questions.

## The CLI

`grill.js` is a Node.js script (needs `node` ≥ 22 on the machine you run it on). Invoke it through node, passing this directory's path:

```
node "<skill_dir>/grill.js" <command> [flags]
```

The CLI talks to the production Hub by default. Large input goes via stdin (`--file -`) or a heredoc — never inline for big batches.

If `node` is unavailable, fall back to grilling me in plain terminal chat: ask one branch's questions, wait, proceed. Keep the same one-branch-at-a-time discipline.

### Commands

| Command | API | Use |
| --- | --- | --- |
| `create` | `POST /sessions` | Create a session + first branch's questions |
| `poll <id>` | `GET .../response?wait=` (loop) | Block until I submit answers |
| `push <id>` | `POST .../rounds` | Push the next branch's questions |
| `complete <id>` | `PATCH /sessions/{id}` | End the session (after shared understanding) |
| `cancel <id>` | `PATCH /sessions/{id}` | Abort (I abandoned, context lost, etc.) |
| `status <id>` | `GET /sessions/{id}` | Query session state |

Flags: `--file -\|<path>` (input, default stdin), `--inline <json>` (small only), `--json [fields]` (machine-readable stdout, optional field filter), `--wait <sec>` (`poll` total timeout, default 600), `--round <n>` (poll a specific round), `--reason <enum>` + `--detail <text>` (cancel).

### Loop

`create` and `push` return immediately — they do **not** wait. Always split into three steps so you can surface the URL to me before blocking:

1. **Create** (or push) — returns at once with the session URL.
2. **Show me the URL** in the TUI (Markdown), then wait for me to open it and answer.
3. **Poll** — blocks until I submit, then prints my Response JSON.

```
# First branch — create returns immediately with the URL
URL=$(node "<skill_dir>/grill.js" create --json url <<'EOF'
{ ...grilling for first branch... }
EOF
)
# → tell me the URL in the TUI (Markdown), e.g. "Answer round 1 here: $URL"
node "<skill_dir>/grill.js" poll <id> --wait 600   # blocks until I submit

# Each subsequent branch: push (returns at once), show the same URL, poll
node "<skill_dir>/grill.js" push <id> <<'EOF'
{ ...grilling for next branch... }
EOF
node "<skill_dir>/grill.js" poll <id> --wait 600   # blocks until I submit

# ...repeat until the tree is resolved...
node "<skill_dir>/grill.js" complete <id>
```

Never pass `--wait` to `create` or `push`: it blocks those calls and denies you the chance to print the URL before waiting. The URL stays the same across rounds — the browser reloads to the next branch automatically, so you only need to point me at it once per session (and can remind me for later rounds).

## The Grilling JSON (you author this)

Read `schemas/grilling.json` for the authoritative schema. Quick reference:

- Top level: `name`, optional `description`, optional `additional_notes` (`{label?, placeholder?, max_length?, required?}` — a global free-text box after all questions), and `questions[]` (1–64 items).
- Each question: `id` (snake_case, unique within the round), `header` (short UI label), `text` (full question), `type` (`single` \| `multi` \| `text`).
- `single`/`multi` need `options[]` (each `{label, description?}`, min 2) — **except** `single` + `variant: "yesno"`, which renders fixed Yes/No buttons and omits `options`.
- `recommended`: your recommended choice. Semantics depend on `variant`:
  - `variant: "default"` (radio, the default) → **0-based index** into `options`.
  - `variant: "rating"` → the **rating value** (1..=`rating_max`, default max 5). No `options` array.
  - `variant: "yesno"` → usually omitted; if present, `0` = no, `1` = yes.
- `explanation`: why you recommend it — shown inline next to the recommendation. Always pair it with `recommended`.
- `required` (default true), `allow_custom_text` (default true, adds a per-question notes box), `placeholder` + `max_length` (for `text`).

Example, one branch (auth approach) as one round:

```json
{
  "name": "Auth approach",
  "description": "Locking down the authentication strategy before we touch code.",
  "questions": [
    {
      "id": "q_auth_scheme",
      "header": "Auth",
      "text": "Which authentication scheme should we use?",
      "type": "single",
      "options": [
        { "label": "JWT, stateless", "description": "Signed tokens; no server session store." },
        { "label": "Server sessions", "description": "Opaque session ID in a DB/Redis." },
        { "label": "OAuth 2.0 / OIDC", "description": "Delegate to an IdP." }
      ],
      "recommended": 0,
      "explanation": "Stateless JWT fits our horizontally-scaled, read-heavy API; refresh tokens cover revocation."
    },
    {
      "id": "q_token_storage",
      "header": "Token store",
      "text": "If JWT, where do we keep refresh-token allowlist state?",
      "type": "multi",
      "required": false,
      "options": [
        { "label": "Redis" },
        { "label": "Postgres" },
        { "label": "None (short TTL only)" }
      ],
      "recommended": 0,
      "explanation": "Redis gives sub-ms revocation checks; pair with short access-token TTL."
    }
  ]
}
```

## Reading the answers (critical)

`poll` returns my answers on **stdout as JSON**. The CLI normalizes everything to exit codes — **do not judge by exit code alone**, parse the JSON:

- **Exit 0, no `status` field** → I submitted answers. Read `answers` (keyed by question `id`; each has `selected` — string for `single`/`text`, string[] for `multi`, `"yes"`/`"no"` for yesno, numeric string for rating — and optional `custom_text`). `additional_notes` is the global notes box, null if empty.
- **Exit 0, `status: "cancelled"`** → I cancelled in the browser. Read `reason`. There are no answers; ask whether to restart or stop.
- **Exit 75** → timeout (`--wait` exhausted, I was slow). Ask whether to keep waiting, then `poll <id> --wait 600` again (within the session's 60-min TTL).
- **Exit 76** → session expired (60-min TTL hit). Unrecoverable; start a new session if we're not done.
- **Exit 64** → your Grilling JSON was malformed or failed schema validation. The CLI prints a hint to stderr — fix the JSON and retry. Never edit `grill.js`.
- **Exit 1 / network errors** → transient; retry, or fall back to terminal chat.

stdout is pure JSON (parse it directly); stderr has human-readable progress/warnings. `2>/dev/null` gives clean JSON.

## Closing the session

When we reach shared understanding:

1. Present a **terminal summary** — one line per decision: the choice and the reasoning. This is terminal-only; do not push it to the browser.
2. Wait for my explicit confirmation (ok / 确认 / yes / LGTM / 没问题 / proceed). Do not treat silence or vague replies as consent.
3. On confirmation, run `node "<skill_dir>/grill.js" complete <id>`. This closes the browser session cleanly.

If I abandon the grilling or you lose context, run `node "<skill_dir>/grill.js" cancel <id>` so the session doesn't linger until TTL.
