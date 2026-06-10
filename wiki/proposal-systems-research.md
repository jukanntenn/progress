# Proposal Systems Research

Research on five open-source proposal tracking systems: EIPs, ERCs, PEPs, Rust RFCs, and Django DEPs. Based on spec document analysis and git history review of actual repositories.

## 1. EIP (Ethereum Improvement Proposals)

**Repository**: `ethereum/EIPs` · **Spec**: `EIPS/eip-1.md`

### Format
YAML frontmatter in Markdown files (`EIPS/eip-*.md`). All 926 EIP files use YAML frontmatter; none use any other format. Frontmatter `eip:` number always matches the filename number (verified: 0 mismatches).

Standard frontmatter:
```yaml
---
eip: 1559
title: Fee market change for ETH 1.0 chain
author: Vitalik Buterin, Eric Conner, ...
discussions-to: https://ethereum-magicians.org/t/...
status: Final
type: Standards Track
category: Core
created: 2019-04-13
requires: 2718, 2930
last-call-deadline: 2021-11-03
---
```

Moved stub frontmatter (minimal — only 3 fields):
```yaml
---
eip: 1062
category: ERC
status: Moved
---
```

The `requires` field is comma-separated when multiple: `requires: 152, 1108, 1344, 1716, 1884, 2028, 2200`.

### Spec-Defined Statuses
| Status | Description | Terminal? |
|---|---|---|
| Idea | Pre-draft, not in repo | N/A |
| Draft | First formally tracked stage | No |
| Review | Ready for peer review | No |
| Last Call | Final review window before Final | No |
| Final | Completed standard | Yes |
| Stagnant | Inactive ≥6 months, may resurrect | No |
| Withdrawn | Author withdrew, cannot resurrect | Yes |
| Living | Continuously updated (e.g. EIP-1) | Yes |

### Real-World Statuses (926 files)
| Status | Count | Notes |
|---|---|---|
| Moved | 365 | **Not in spec** — ERCs migrated to separate repo |
| Stagnant | 245 | Most common "active" non-terminal status |
| Final | 138 | |
| Draft | 127 | |
| Withdrawn | 34 | |
| Review | 10 | |
| Last Call | 5 | |
| Living | 3 | |

### Types & Categories
- **Types** (from YAML frontmatter only): Standards Track (498), Meta (43), Informational (20)
- **Categories** (Standards Track only): Core (413), ERC (365), Interface (58), Networking (27)
- **Extra fields**: `requires`, `last-call-deadline`, `discussions-to`

### Key Deviations from Spec
1. **"Moved" status** — The spec does not define this. All 365 Moved EIPs have `category: ERC` and are stubs pointing to the `ethereum/ercs` repo. These stubs have only 3 frontmatter fields (`eip`, `category`, `status`) — no title, author, type, or created date.
2. **Stagnant dominates** — 245 EIPs are stagnant (26% of all EIPs), suggesting the 6-month inactivity rule is enforced automatically.
3. **No EIP has "Rejected" status** — The spec does not define it, and no EIP file uses it. EIPs are only ever Withdrawn, not Rejected.

---

## 2. ERC (Ethereum Request for Comments)

**Repository**: `ethereum/ercs` · **Spec**: Same EIP-1

### Format
Identical to EIPs (YAML frontmatter), but filenames use `erc-` prefix. Critically, ERCs still use the `eip:` header field (not `erc:`), sharing the same numbering namespace.

```yaml
---
eip: 20
title: Token Standard
type: Standards Track
category: ERC
status: Final
created: 2015-11-19
---
```

### Real-World Statuses (597 files)
| Status | Count |
|---|---|
| Draft | 215 |
| Stagnant | 165 |
| Final | 138 |
| Review | 57 |
| Last Call | 14 |
| Withdrawn | 8 |

### Key Observations
- All ERCs are `type: Standards Track, category: ERC`
- ERCs have a higher Draft ratio (36% vs 14% for EIPs), suggesting a newer, more actively growing ecosystem
- ERCs were historically in the EIPs repo and were migrated — this is the source of the "Moved" status in EIPs
- Same parser can handle both EIPs and ERCs (same format, same `eip:` header)
- The ERCs repo also contains `eip-1.md` (a copy of the EIP-1 spec), not an ERC — parser must handle this via `file_pattern` filter

---

## 3. PEP (Python Enhancement Proposals)

**Repository**: `python/peps` · **Spec**: `peps/pep-0001.rst`

### Format
reStructuredText with plain `Key: Value` headers (`pep-*.rst`). Note: headers are **not** RST field list format (`:Key: Value`) — they use simple `Key: Value` lines. All 726 PEP files have both Title and Status fields. Header `PEP:` number always matches the filename number (verified: 0 mismatches after zero-padding normalization).

18 PEPs also have auxiliary directories (e.g. `pep-0001/` containing `process_flow.svg`) — parser must skip directories and only parse `.rst` files.

```rst
PEP: 733
Title: An Evaluation of Python's Public C API
Author: [28 authors listed, one per line]
Status: Final
Type: Informational
Topic: Packaging
Created: 16-Oct-2023
Post-History: ...
Discussions-To: ...
Resolution: ...
Requires: ...
Python-Version: ...
```

Headers can appear well into the file — PEP-733 has `Status:` on line 31 due to its 28-author list. The `Topic` field can have compound values (e.g. `Topic: Governance, Packaging`).

### Spec-Defined Statuses
| Status | Description | Terminal? |
|---|---|---|
| Draft | Initial state | No |
| Accepted | Approved for implementation | No |
| Provisional | Accepted but needs more feedback | No |
| Deferred | No progress, may resume | No |
| Final | Implemented and released | Yes |
| Active | Continuously maintained (Info/Process only) | Yes |
| Rejected | Rejected | Yes |
| Withdrawn | Author withdrew | Yes |
| Superseded | Replaced by another PEP | Yes |

### Real-World Statuses (726 files)
| Status | Count | Notes |
|---|---|---|
| Final | 357 | Most common |
| Rejected | 130 | |
| Withdrawn | 70 | |
| Draft | 43 | |
| Active | 38 | |
| Deferred | 36 | |
| Accepted | 26 | |
| Superseded | 25 | |
| April Fool! | 1 | **Not in spec** — PEP-401 |

### Types & Topics
- **Types**: Standards Track (569), Informational (104), Process (53)
- **Topics** (optional): Packaging (99), Typing (44), Release (27), Governance (23)

### Key Deviations from Spec
1. **"April Fool!" status** — PEP-401 ("BDFL Retirement") uses this. The spec does not define it.
2. **No Provisional PEPs in practice** — The spec defines "Provisional" but no current PEP uses it. This is a theoretical status.
3. **Topic field** — Not part of the formal spec status/type model, but widely used for categorization.
4. **Post-History** — A PEP-unique field tracking discussion thread history, not present in other systems.

---

## 4. RFC (Rust Request for Comments)

**Repository**: `rust-lang/rfcs` · **Spec**: `README.md`

### Format
Markdown files in `text/NNNN-descriptive-slug.md`. Template has no status field.

```markdown
- Feature Name: my_awesome_feature
- Start Date: 2024-01-01
- RFC PR: [rust-lang/rfcs#1234](...)
- Rust Issue: [rust-lang/rust#5678](...)
```

### The Fundamental Difference
**RFC files contain no status field.** The RFC lifecycle is PR-based:

1. Author submits PR → file added as `text/0000-*.md`
2. Community reviews via PR comments
3. Sub-team enters FCP (Final Comment Period, 10 days)
4. PR merged → file renamed to `text/<PR-number>-*.md`, status = "merged/active"
5. OR PR closed → status = "rejected" or "postponed"

### Implications for Tracking
- **Cannot determine status from file content alone.** The current code sets status="unknown", which is correct.
- **Status tracking requires GitHub PR metadata** (PR state, labels, merge status).
- **The file's presence in `text/` means it was merged** (PR was accepted). Closed/rejected RFCs are not in the repo.
- **Postponed RFCs** get a "postponed" label on the closed PR. The file itself is never added to `text/`.

### Real-World Data
- 633 RFC files in `text/` directory across 632 unique numbers (one duplicate: RFC 2071 has two files)
- Files range from `0001` to `3946`
- RFC 2071 has a redirect stub (`2071-impl-trait-type-alias.md` → "Moved to [2071-impl-trait-existential-types.md]") — same pattern as EIP Moved
- 10 RFC files contain body-text notes about being superseded or withdrawn after merge (e.g. "This RFC was previously approved, but later **withdrawn**") — not detectable from structured metadata
- Files with `---` inside contain Markdown horizontal rules, not YAML frontmatter

### Key Deviations from Spec
1. **No file-level status at all** — This is by design, but means we must treat RFCs fundamentally differently from other proposal types.
2. **Postponed is a PR label, not a file state** — Can't detect from repo alone.
3. **Once merged, the file is essentially "Accepted"** — But 10 RFCs were later superseded or withdrawn after merge, noted only in body text, not in any structured field. Cannot be detected programmatically.
4. **RFC 2071 duplicate** — One number has two files, one being a redirect stub. Parser must handle this (e.g. by using file_path as secondary key).

---

## 5. DEP (Django Enhancement Proposals)

**Repository**: `django/deps` · **Spec**: `final/0001-dep-process.rst`

### Format
RST files use `:Key: Value` RST field list headers. Markdown files (1 file: `0018-mailers.md`) use YAML frontmatter (`---`). **Organized into status directories.** The DEP spec provides both an RST template and a Markdown template.

DEP number in header does not include zero-padding (`DEP: 7` not `DEP: 0007`), while filenames do (`0007-dependency-policy.rst`).

```
deps/
├── draft/         → status: Draft
├── accepted/      → status: Accepted
├── final/         → status: Final
├── rejected/      → status: Rejected (currently empty)
├── withdrawn/     → status: Withdrawn
└── superseded/    → status: Superseded
```

```rst
==============================
DEP 0009: Async-capable Django
==============================

:DEP: 0009
:Author: Andrew Godwin
:Implementation Team: Andrew Godwin
:Shepherd: Andrew Godwin
:Status: Accepted
:Type: Feature
:Created: 2019-05-06
```

### Spec-Defined Statuses
| Status | Description | Terminal? |
|---|---|---|
| Draft | Initial submission | No |
| Accepted | Approved by Steering Council | No |
| Final | Implementation complete | Yes |
| Rejected | Rejected | Yes |
| Withdrawn | Author withdrew | Yes |
| Superseded | Replaced by another DEP | Yes |

### Real-World Data (24 files)
| Status (from header) | Count |
|---|---|
| Final | 11 |
| Draft | 6 |
| Accepted | 5 |
| Withdrawn | 1 |
| Superseded | 1 |

### Key Deviations from Spec
1. **DEP-7 appears in both `draft/` and `final/`** — Different proposals (`0007-dependency-policy.rst` in draft, `0007-official-projects.rst` in final). The spec says DEPs move between directories, but this shows numbers can be reused across different proposals.
2. **`draft/content-negotiation.rst`** — No DEP number in filename. Only has inline headers without `:DEP:` field.
3. **Header vs directory mismatches** — Two DEPs have status headers that disagree with their directory:
   - `final/0014-background-workers.rst` → header says `Accepted`, directory says `final`
   - `final/0044-clarify-release-process.rst` → header says `Draft`, directory says `final`
4. **Dual status indicators** — Both the directory location AND the file's `:Status:` header indicate status. The DEP-1 spec does not specify which takes precedence.
5. **Very small corpus** — Only 24 DEPs exist. Django's DEP process is used sparingly.

---

## Cross-System Comparison

### Status Mapping

| Phase | EIP/ERC | PEP | RFC | DEP |
|---|---|---|---|---|
| Development | Draft | Draft | PR open | Draft |
| Review | Review / Last Call | Accepted | FCP | — |
| Approved | Final | Final | Merged | Final |
| Living | Living | Active | — | — |
| Inactive | Stagnant | Deferred | Postponed | — |
| Abandoned | Withdrawn | Withdrawn | Closed | Withdrawn |
| Rejected | — | Rejected | Closed | Rejected |
| Replaced | — | Superseded | — | Superseded |
| Relocated | Moved | — | — | — |
| Novelty | — | April Fool! | — | — |

### Structural Differences

| Aspect | EIP/ERC | PEP | RFC | DEP |
|---|---|---|---|---|
| File format | Markdown + YAML | reStructuredText | Markdown | rst (23) + md (1) |
| Metadata format | YAML frontmatter | Plain `Key: Value` headers | Bullet list (`- Key: Value`) | RST field list (`:Key: Value`) or YAML frontmatter |
| Status source | File header | File header | PR state (not in file) | File header + directory path |
| Number in header | Yes (`eip: N`) | Yes (`PEP: N`, no padding) | No (from filename) | Yes (`:DEP: N`, no padding) |
| File naming | `eip-N.md` / `erc-N.md` | `pep-NNNN.rst` | `NNNN-slug.md` | `NNNN-slug.rst` or `NNNN-slug.md` or `slug.rst` (no number) |
| Categorization | Type + Category | Type + Topic | — | Type |

### Common Patterns
1. **All systems use a numbered proposal file** in a VCS repository
2. **All systems have Draft → Approved → Final lifecycle** (RFC is implicit)
3. **Status is generally in file metadata** (except RFC)
4. **Terminal states are Final/Rejected/Withdrawn/Superseded**
5. **Files are rarely deleted** — they transition to terminal states

### Critical Edge Cases
1. **EIP "Moved" stubs** — 365 files are minimal stubs (only `eip`, `category`, `status` in frontmatter — no title, author, type, created). Parser must handle missing required fields gracefully.
2. **PEP "April Fool!"** — Non-standard status (PEP-401, "BDFL Retirement")
3. **RFC no status** — Requires fundamentally different tracking approach. 10 RFCs were withdrawn/superseded after merge but this is only noted in body text.
4. **DEP header vs directory mismatch** — DEP-0014 (`Accepted` in `final/`) and DEP-0044 (`Draft` in `final/`)
5. **ERC uses `eip:` header** — Same parser as EIP but different repo and file prefix. ERCs repo also contains `eip-1.md` (spec doc, not an ERC).
6. **DEP number reuse** — DEP-7 has two different proposals in different directories
7. **PEP no Provisional in practice** — Spec-defined status never used
8. **DEP file without number** — `draft/content-negotiation.rst` has no DEP number in filename or header
9. **RFC 2071 duplicate** — One number, two files (one is a redirect stub)
10. **DEP dual format** — RST files use `:Key: Value`, MD files use YAML frontmatter
11. **PEP deep headers** — Headers can appear 30+ lines into the file (PEP-733 has 28 authors). Parser must scan deep enough.
12. **PEP auxiliary directories** — 18 PEPs have companion directories (e.g. `pep-0001/`). Parser must only process `.rst` files.
13. **EIP has no "Rejected" status** — EIPs are Withdrawn or Stagnant, never Rejected. The comparison table reflects this gap.
