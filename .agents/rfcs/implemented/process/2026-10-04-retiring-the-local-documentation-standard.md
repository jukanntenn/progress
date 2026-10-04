# RFC: Retiring the local documentation standard for the hdsh harness

Status: implemented

English | [中文](2026-10-04-retiring-the-local-documentation-standard.zh.md)

## Problem

progress carried its own documentation standard: the `doc_sync.py` gate aggregator over five `verify_*.py` gates, word ceilings in `scripts/doc_budgets.manifest.json`, decision records in `.agents/prfcs/`, and the `README.md`/`README_zh.md` naming convention. Adopting the hdsh harness beside that standard would run two gate sets over one corpus: the local wrap gate parses `<!-- hdsh:slot -->` marker comments as prose, the local pairing scope cannot express `README.zh.md` triplets, and two decision-record trees would violate the one-home-per-fact rule the harness installs. The harness's own adoption manual requires the retirement in the same adoption rather than a side-by-side dual standard.

## Decision

The local standard is retired in the same change that adopts the harness. `scripts/doc_sync.py`, the five `verify_*.py` gates, `doclib.py`, and `scripts/doc_budgets.manifest.json` are deleted together with the prek `doc-check` hook and the CI step that ran them; the hdsh gates (pairing, RFC format, wrap, links, budgets, adoption completion) replace both, in the prek `hdsh` group and in CI pinned to the adopted ref. The six implemented PRFC pairs moved from `.agents/prfcs/implemented/` into `.agents/rfcs/implemented/{architecture,process}/` with headers rewritten to the RFC format and `.i18n.yaml` records added, completing their triplets. Word ceilings folded into `.hdsh/docs.manifest.json`: `AGENTS.md` 2600 and `docs/AGENTS.md` 1100 absorb the standing-orders and documentation-standard growth from the harness merge with the required 5% headroom; `docs/development.md` rises from the template's 300 to 900 because the existing 851-word contributor guide stays the document of record; `web/AGENTS.md` keeps its 300 ceiling. `README_zh.md` is renamed `README.zh.md` and recorded as the pairing counterpart of `README.md`, and the whole `docs/` corpus gains Chinese counterparts under the pairing contract.

## Alternatives considered

**Running both standards side by side.** Zero migration cost, but the harness forbids it by design: the local wrap gate fights the transplanted slot-marker comments, and every gate would exist twice with slightly different rules — the drift the gates exist to prevent.

**Keeping `.agents/prfcs/` beside `.agents/rfcs/`.** Rejected for one home per fact: two decision-record trees means two inventories to grep and two formats to enforce, and the PRFC format gate was itself part of the retired standard.

## Consequences

- The hdsh gates are the only documentation gates; upgrades rerun `hdsh adopt apply` under the newer ref and redirect upstream.
- The retired gate names (`doc_sync`, `verify_md_*`, `verify_prfc_format`) live only in git history and in the prose of the records that decided them.
- The ceiling raises above are the justification the budget gate requires; later raises follow the standing relocate/condense/raise order.
- The pre-adoption record `2026-08-22-prfcs-tree-and-contract.md` describes the retired `.agents/prfcs` tree; this record, not that one, governs where decisions live now.
