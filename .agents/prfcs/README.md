# Progress Request for Comments (PRFC)

English | [中文](README.zh.md)

PRFCs are progress's RFCs: durable proposals and decision records — the _why_, _what we gave up_, and the parts code and specs cannot carry. Specs describe current state; PRFCs explain why that state is what it is.

## Layout and naming

Every PRFC lives at `.agents/prfcs/{lifecycle}/yyyy-mm-dd-topic-title.md`. The date is when the topic was first proposed (per git history). The lifecycle tree is the inventory — browse it or grep the repository; there is no index file to maintain.

- **`proposed/`** — proposals reviewed before implementation. Not yet built, or only partly built.
- **`implemented/`** — the decision shipped. The file records what was decided and what was rejected, in the present tense. When code later renames a file or changes a default, update the PRFC's facts (paths, names, structure) in the same change — but never edit it into a different decision; supersede it with a new PRFC and cross-link both.
- **`rejected/`** — the proposal was considered and declined. Keep one only while its rationale prevents a tempting mistake; otherwise delete it.

Cross-references between PRFCs use relative Markdown links, never bare prose, so [`verify_md_links`](../../scripts/verify_md_links.py) can check them and they survive moves between folders.

## When to write one

Every non-trivial change adds or updates at least one PRFC in the same PR. A change is non-trivial when it alters behavior, architecture, a contract shared across files, tooling, testing strategy, an on-disk or wire format, or anything a maintainer may reasonably revisit. Purely mechanical or local edits are exempt. Updating the PRFC that already owns the decision satisfies the rule — do not create a duplicate; grep `.agents/prfcs/` for the topic first.

## The file format

The header block is exactly:

```markdown
# PRFC: <title>

Status: <status>
```

The `Status:` value must agree with the folder and takes one of three forms: `proposed`, `implemented`, or `rejected — <why, in one line>` (the rejection reason is the fact readers come for). The body opens with `## Problem`, written to stand without the solution.

`implemented/` continues `## Decision` (present tense, what shipped) … `## Alternatives considered` … `## Consequences`. Proposal-era headings — `## Proposal`, `## Plan`, `## Migration plan`, `## Acceptance criteria` — are rejected here by the format gate.

`proposed/` continues `## Proposal` … `## Alternatives considered` … `## Acceptance criteria` … `## Risks`. A proposal may speak in the future tense while the work is unbuilt.

`rejected/` keeps whatever proposal-time sections it had, frozen; the verdict lives on the `Status:` line.

Every record is a bilingual pair: the English original `foo.md` with a `.zh.md` twin beside it — same skeleton, machine tokens and section headings in English, a header switcher linking the twin — and the pair updates together ([tree-contract PRFC](./implemented/2026-08-22-prfcs-tree-and-contract.md)).

**`## Alternatives considered` is mandatory in every PRFC** — one bold-led paragraph per genuine alternative and why it lost. A decision recorded without what it beat invites re-litigation, which is the failure PRFCs exist to prevent. Alternatives are recorded as they were argued, never invented after the fact.

Moving a file between lifecycle folders means updating its `Status:` line and re-satisfying that folder's skeleton in the same change, both languages of the pair: `proposed/` → `implemented/` rewrites `## Proposal` into a present-tense `## Decision` and folds `## Acceptance criteria`/`## Risks` into `## Consequences`; `proposed/` → `rejected/` only adds the reason to `Status:` and freezes the file.

[`verify_prfc_format.py`](../../scripts/verify_prfc_format.py) enforces all of the above; it runs as part of [`doc_sync.py`](../../scripts/doc_sync.py).
