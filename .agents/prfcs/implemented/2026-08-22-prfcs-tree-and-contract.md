# PRFC: The .agents/prfcs tree and its contract

Status: implemented

English | [中文](2026-08-22-prfcs-tree-and-contract.zh.md)

## Problem

Decision rationale had no home in progress. `specs/redesign/00-17` is the authoritative design contract — current state, what the system is — and is edit-gated ("Ask first" in the root `AGENTS.md`); `PRINCIPLES.md` carries behavioral values, not decisions; commit messages and git history cannot carry a decision across the later changes that touch it. The result is the failure RFC systems exist to prevent: why a design is what it is survives only in memory, alternatives that lost get re-argued from scratch, and a reviewer cannot answer "why not X?" without archaeology. The reference adaptation — markpost's `.agents/mrfcs/`, itself adapted from deepseek-harness's agent notes — demonstrated the mechanism at comparable scale, with selective porting as its founding verdict.

## Decision

PRFCs — progress's RFCs: durable proposals and decision records, the _why_, the alternatives that lost, and what code and specs cannot carry — live at `.agents/prfcs/{proposed,implemented,rejected}/yyyy-mm-dd-topic-title.md`; the date is when the topic was first proposed, per git history. The tree is its own inventory: browse it or grep the repository; there is no index file.

Two documents carry the contract with orthogonal jobs: [`README.md`](../README.md) is the normative contract (layout, lifecycle, file format) with its [`README.zh.md`](../README.zh.md) twin; [`AGENTS.md`](../AGENTS.md) holds standing orders only — grep for a prior home before writing, never edit a record into a different decision, keep the pair in sync — each a trigger linking to its rule's home.

The file format is enforced by [`scripts/verify_prfc_format.py`](../../../scripts/verify_prfc_format.py), stdlib Python. The header block is exactly `# PRFC: <title>` and `Status: <status>`; the status agrees with the folder (`proposed`, `implemented`, or `rejected — <why, in one line>`); the body opens with `## Problem`, written to stand without the solution. `proposed/` continues `## Proposal` … `## Alternatives considered` … `## Acceptance criteria` … `## Risks`. `implemented/` continues `## Decision` (present tense, paths and names matching the code today) … `## Alternatives considered` … `## Consequences`. `rejected/` keeps its proposal-time skeleton frozen; the verdict lives on the `Status:` line. `## Alternatives considered` is mandatory in every record — one bold-led paragraph per genuine alternative and why it lost, recorded as actually argued, never invented after the fact. Moving a file between folders means updating its `Status:` and re-satisfying the target folder's skeleton in the same change.

Every record is a bilingual pair: `foo.md` beside `foo.zh.md`, same skeleton, machine tokens and section headings in English, a header switcher linking the twin, and the pair updates together. Relative links inside a record must resolve; references to things that do not exist yet are written as code literals and become links in the change that lands them.

Boundary with `specs/redesign/`: specs describe what is — the design contract, edit-gated; PRFCs record why, and what was given up. Neither restates the other; each links.

Trigger rule: every non-trivial change adds or updates at least one PRFC in the same PR — non-trivial meaning it alters behavior, architecture, a contract shared across files, tooling, testing strategy, or an on-disk or wire format, anything a maintainer may reasonably revisit. Purely mechanical or local edits are exempt. Updating the PRFC that already owns the decision satisfies the rule; grep `.agents/prfcs/` for the topic first.

The prek global exclude is narrowed to `.agents/(skills|hooks)/` (see the [gates PRFC](2026-08-22-documentation-gates-and-corpus-wiring.md)), so the tree is gated at commit and in CI.

## Alternatives considered

**Port deepseek-harness wholesale — class folders (feature/bug-fix/simplification/architecture/process/testing), a frozen sealed archive with sidecar hashes, per-note `.md` + `.zh.md` + `.i18n.yaml` triplets, per-lifecycle AGENTS.md files.** It lost: markpost's founding verdict already rejected it for a corpus an order of magnitude smaller than the reference, and progress's corpus starts smaller still; triplet and manifest upkeep taxes every edit while buying nothing at this size. Pieces arrive on trigger signals, never wholesale.

**The ADR convention (`docs/adr/`).** It lost: the corpus is agent-first in both authorship and readership; `.agents/` is the load path agent tooling already reads (skills today, PRFCs now), and decision memory belongs beside the workflows that consume it.

**Record decisions inside `specs/redesign/` prose.** It lost: specs are the edit-gated current-state contract; folding rationale into them mixes what-is with why-it-is, and the edit gate leaves day-to-day decisions with nowhere to land without a review ceremony.

**A generated index file.** It lost: the lifecycle tree is the inventory and grep is the search; an index is a second copy of the truth that must be kept in step.

## Consequences

The tree landed with its README pair, `AGENTS.md`, and the format gate in one change; the gate passes over the whole tree including this record's pair, and a deliberately malformed record (missing twin, wrong status, proposal-speak in `implemented/`) fails it — drilled by hand and reverted. CI runs the same command as local (`uv run python scripts/doc_sync.py`, [gates PRFC](2026-08-22-documentation-gates-and-corpus-wiring.md)). This record and its two siblings bootstrapped the lifecycle: written as `proposed/` pairs, reviewed, implemented, then moved and rewritten into `implemented/` skeletons in the same change — the mechanism exercised its own introduction. The costs accepted: every non-trivial change carries a new or updated record (the exemption clause and grep-first keep the duty proportional); every record update touches both languages of the pair — the maintainer works in Chinese, so the twin is a feature, not a surcharge; and the format gate may misjudge, in which case the gate change ships in the same change as the need that motivated it and says so here. The [config PRFC](2026-06-26-config-database-single-source.md) back-fills the durable why of the 2026-06 config refactor from a deleted point-in-time document — the pattern for dispositions under the [gates PRFC](2026-08-22-documentation-gates-and-corpus-wiring.md).
