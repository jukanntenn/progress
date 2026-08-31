# AGENTS.md — The documentation standard

This file defines where documentation lives and the writing rules every gate enforces. `uv run python scripts/doc_sync.py` validates (CI runs the full corpus; the prek `doc-check` hook runs staged files only).

## Tiers: one fact, one home

| Tier                                                             | Job                                                                        |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `README.md` / `README_zh.md`                                     | User-facing product docs                                                   |
| Root `AGENTS.md`                                                 | Standing orders for every session, linking each rule's home                |
| Subtree `AGENTS.md` (`web/`, this file)                          | Orders specific to that subtree; never repeat the root                     |
| `PRINCIPLES.md`                                                  | Live behavioral values the skills operate by                               |
| `specs/redesign/`                                                | Authoritative design contract (00-17, edit-gated; see root AGENTS.md)      |
| `docs/`                                                          | Operation guides (development, deployment, testing, users, CI); this file owns the doc rules |
| `.agents/prfcs/`                                                 | progress's RFCs — proposals and decision records ([README](../.agents/prfcs/README.md)) |
| `.agents/skills/`                                                | Agent workflows (mirrored to `.zcode/skills/` by `scripts/sync_agent_instructions.py`) |

Elsewhere, link; never restate. Rationale → `.agents/prfcs/`; procedures → `docs/`; system facts → `specs/redesign/`; rules an agent needs every session → `AGENTS.md`.

## Rules and gates

1. **Current state only** (README, docs) — no `previously` / `no longer` / `已移除` / `不再` narration; link the owning PRFC for the why. `specs/redesign/` is out of scope by design: its comparative voice is part of the redesign contract, and "legacy" is product vocabulary here — `verify_md_current.py`.
2. **Machine-checkable links.** Relative Markdown paths with resolving targets and `#fragment` anchors; never bare filenames — `verify_md_links.py`.
3. **One physical line per paragraph.** Soft-wrap in the editor; code blocks, tables, and lists keep their structure — `verify_md_wrap.py`.
4. **PRFC format.** Header, Status-agrees-with-folder, `## Problem` opener, mandatory `## Alternatives considered`, and a bilingual `.zh.md` twin per record — `verify_prfc_format.py`.
5. **Word budgets.** The agent-instruction files carry `wc -w` ceilings in [`scripts/doc_budgets.manifest.json`](../scripts/doc_budgets.manifest.json); a budgeted file that is missing fails the gate — `verify_doc_budgets.py`. On red: relocate, condense, raise the ceiling last with a justified manifest diff.

Bilingual scope: the PRFC tree (records plus its README pair) is bilingual by contract; the rest of the corpus is English with the `README.md`/`README_zh.md` pair as-is, and expands only on a trigger signal through a PRFC.

Outside gate scope: the app's gettext catalogs (`src/progress/locales/`, owned by `check_translations.py`), generated artifacts (`web/openapi.json`, `web/src/api/schema.ts`), the `.zcode/` mirrors, `data/`, and `.local/`.

## Slop to hunt

The same rule stated in two homes (a subtree `AGENTS.md` restating the root is the common case); narrated history in operation guides; hand-restated catalogs where a script is authoritative; paragraph walls carrying several rules; one side of a language pair edited without its twin. Keep one home, link the rest.
