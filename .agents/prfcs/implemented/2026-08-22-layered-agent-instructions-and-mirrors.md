# PRFC: Layered agent instructions, direction-free mirrors, and single-source skills

Status: implemented

English | [中文](2026-08-22-layered-agent-instructions-and-mirrors.zh.md)

## Problem

The root `AGENTS.md` loaded in every agent session at 2,173 words: frontend commands, Playwright e2e instructions, CI workflow inventories, user-management and migration procedures — operational detail that belongs to the docs tier — sat beside the genuine standing orders, and nothing mechanical bounded the file's growth (the reference project's own record documents prose discipline failing without a budget backstop). `CLAUDE.md` claimed to "mirror AGENTS.md verbatim" with no tooling behind the claim — and the claim was already false in HEAD: the committed pair disagreed (a missing shipping note, a stale `release.yml` line). The skills existed as two manual mirrors — `.agents/skills/` (8 skills) and `.zcode/skills/` (7) — with no declared source and no gate; they had already drifted: `grilling-sleek` existed only on the `.agents` side.

## Decision

**Direction-free instruction mirrors.** [`scripts/agentlib.py`](../../../scripts/agentlib.py) resolves direction per pair against git HEAD — never mtime, which clone and checkout reset: exactly one side differing from HEAD means that side is copied over the other, so fresh updates stale; equal contents pass; both sides changed and disagreeing is a conflict the tooling refuses to guess through. A path absent from HEAD counts as changed on its side, which bootstraps new pairs. [`scripts/check_agent_instructions.py`](../../../scripts/check_agent_instructions.py) is the gate (self-healing: copies the fresh side and stages the stale twin), [`scripts/sync_agent_instructions.py`](../../../scripts/sync_agent_instructions.py) the fixer; the prek `agent-instructions-sync` hook runs the gate at commit.

**Mirror matrix.** Root `AGENTS.md` ↔ `CLAUDE.md` and `web/AGENTS.md` ↔ `web/CLAUDE.md` are direction-free pairs. Skills are single-source: `.agents/skills/` is the source (the agents.md ecosystem's standard path, already the superset), mirrored one-way to `.zcode/skills/`, a tool-specific load path — directional, because a mirror of a copy is not a pair of equals; the gate reports mirror drift by file and names the source instead of guessing. The same agentlib carries both modes.

**Layering with budgets.** The root keeps what every session needs — identity, tech stack, the layout map, the command index, Standards pointers, Boundaries, Testing/CI summaries, a PRFCs section, and an "Editing these instructions" section stating the mirror contract and the budgets — and shed subtree and operational detail: frontend commands, the frontend stack lines, and the Playwright e2e block moved to the new [`web/AGENTS.md`](../../../web/AGENTS.md); the Users, Proposal Tracking, Database Migrations, and CI/CD sections condensed to pointers into the docs tier (new pages [`docs/users.md`](../../../docs/users.md) and [`docs/ci-cd.md`](../../../docs/ci-cd.md) own their detail). Word ceilings live in [`scripts/doc_budgets.manifest.json`](../../../scripts/doc_budgets.manifest.json), gated by [`scripts/verify_doc_budgets.py`](../../../scripts/verify_doc_budgets.py); a budgeted file gone missing fails the gate. Ceilings sit at the post-split content plus headroom — the root lands at 2,066 `wc -w` words under a 2,300 ceiling (the proposal's 1,400–1,500 estimate undercounted the layout map, which legitimately stays in the root), `web/AGENTS.md` at 235 under 300, `docs/AGENTS.md` under 600, `.agents/prfcs/AGENTS.md` under 150.

`PRINCIPLES.md` stays the live values home. The reference froze its counterpart into an archive, but progress's skills read that file as the operating values (the `iterating` skill names it directly); that part of the adaptation is deliberately not ported.

## Alternatives considered

**Symlink mirrors — the reference's mechanism.** Zero drift by construction, but git stores a symlink as a blob holding the target path, and a Windows checkout without `core.symlinks=true` materializes `CLAUDE.md` as a regular file containing nine bytes of text; nothing constrains contributors to Unix-like checkouts. It lost for the same reason it lost in the reference adaptation.

**Keep one large root file.** Every session pays for detail it does not need, and without a mechanical budget the accretion continues — the load paths already support progressive disclosure (tools merge subtree instruction files along the cwd chain), so layering localizes the context tax.

**Split by stack as aggressively as the reference (subtree AGENTS.md for the backend or `src/progress/integrations/`).** The reference had four technology stacks across three workspaces; progress's backend is one Python package whose integration-plugin rules already live in the root layout map and spec 06. A backend subtree file would restate the root — the exact slop a tier system hunts. Revisit on a trigger signal: integrations authorship becoming a routine activity.

**Directional sync for the AGENTS/CLAUDE pairs.** Directionality is the defect, not a tuning choice: whichever side is named secondary has its edits silently reverted by the fixer, precisely on the side whose tool loads it and whose agent therefore most likely edited it.

**mtime-based direction detection.** Clone and checkout reset mtimes to now, making both sides equally new; content comparison against HEAD is deterministic and depends on no filesystem state.

**Per-tool native rule files (`.cursor/rules` and friends).** One fact gains a home per tool and drifts between them; the mirror keeps one content under per-tool filenames at zero marginal authoring cost.

## Consequences

The mirror matrix was drilled directly: a single-sided edit on either side is detected and fixed (the stale-twin copy staged by the gate), identical edits pass, disagreeing edits fail naming the sides and the reconciliation steps, and adding one side of a new pair bootstraps the twin — the `web/` pair landed exactly that way. The landing also repaired two pieces of pre-existing drift the Problem section names: root `CLAUDE.md` caught up to the rewritten `AGENTS.md`, and `grilling-sleek` reached the `.zcode/skills/` mirror. The costs accepted: the hook mutates staged content, bounded to the deterministic exactly-one-side case (both-sides never guessed); the root carries its layout map openly under a ceiling rather than shrinking artificially — budgets are ceilings, not targets, and raising one takes a justified manifest diff; and editing `.zcode/skills/` directly is overwritten by design, with the gate's error output naming the single source so an agent reading it knows where to edit.
