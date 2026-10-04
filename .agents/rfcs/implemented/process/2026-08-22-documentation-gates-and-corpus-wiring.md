# RFC: Documentation gates, corpus alignment, and local gating wiring

Status: implemented

English | [中文](2026-08-22-documentation-gates-and-corpus-wiring.zh.md)

## Problem

The Markdown corpus had zero mechanical checks: cross-links rotted silently, hard-wrapped paragraphs put reflow noise into every diff, `docs/` carried point-in-time documents narrating finished migrations (`config-refactor.md`, `verification-config-refactor.md`), a manual checklist drifted from reality (stale ports, a removed `truncate` provider, a dead `i18n.md` link), and CI ran no documentation check at all — the drift job covered generated artifacts, not prose. The prek global exclude blocked `^\.agents/` wholesale, so a decision-record tree would land ungated and its format gate would scan zero files while passing green. Commit messages followed Conventional Commits by convention — the git log is consistent — but nothing enforced the format.

## Decision

**Gates.** Stdlib-Python gates in `scripts/`, sharing masking and slug helpers in `doclib.py`: `verify_md_links.py` (relative links resolve, `#fragment` anchors included), `verify_md_wrap.py` (one physical line per paragraph; code blocks, tables, and lists keep their structure), `verify_md_current.py` (current-state prose in README and docs), `verify_prfc_format.py` (shipped with the [tree PRFC](2026-08-22-prfcs-tree-and-contract.md)), and `verify_doc_budgets.py` (shipped with the [layering PRFC](2026-08-22-layered-agent-instructions-and-mirrors.md)). `doc_sync.py` runs them in sequence, keeps each independently runnable, and restricts scope to given file arguments; a staged run expands a file to its bilingual pair.

**Scope, calibrated to this repo.** `verify_md_current` covers `README.md`, `README_zh.md`, and `docs/*.md` — `specs/redesign/` is deliberately out of scope: its comparative voice ("旧→新", "不再用 X") is part of the redesign corpus's contract and it is edit-gated besides, while `docs/` is where stale narration actually lived. `legacy` is deliberately absent from the forbidden markers: the legacy (pre-redesign) build is real product vocabulary here (`scripts/migrate_from_legacy.py`, the one-time migration guide). Links and wrap cover README, `PRINCIPLES.md`, the root and `web/AGENTS.md`, `docs/`, `specs/redesign/`, the PRFC tree, `.agents/skills/` (CI full runs — the global exclude keeps it out of staged runs), and `web/e2e/`; CLAUDE.md mirrors are byte copies and stay unchecked by the same rule.

**Wiring.** The prek `doc-check` hook runs `doc_sync` on staged Markdown only — prek stashes unstaged changes during hook runs, so a wider scan would see a stale tree — excluding the `.zcode/` mirror. The prek global exclude narrows from `^\.agents/` to `.agents/(skills|hooks)/` so the PRFC tree and any future hand-written `.agents/` Markdown are gated by default. CI's drift-checks job (renamed "Drift + docs checks") gains `uv run python scripts/doc_sync.py` — the `check_drift.py` principle, CI and local sharing one command, extends from generated artifacts to prose. `check_drift.py` itself stays pure regenerate-and-diff; prose gates are a different class with their own aggregator.

**Commit-msg gate.** [scripts/check_commit_msg.py](../../../../scripts/check_commit_msg.py) plus a prek `commit-msg` hook (`default_install_hook_types` now installs it) enforce Conventional Commits with optional scope, matching the existing log style and the `commit` skill.

**Corpus alignment.** [docs/AGENTS.md](../../../../docs/AGENTS.md) is the documentation standard's home: a tier map with each rule linked to its gate; the root Standards section points there. The point-in-time documents are dispositioned per file: `config-refactor.md` and `verification-config-refactor.md` are deleted, their durable decisions carried by the [config PRFC](../architecture/2026-06-26-config-database-single-source.md); `manual-verification-checklist.md` is living operational content and stayed, with its stale facts corrected (ports 5000/3000 → 8000/5173, the removed `truncate` provider → leaving `analysis.api_key` empty, the dead `i18n.md` link → `specs/redesign/11-i18n.md`). The hard-wrapped corpus was normalized in the same change (paragraphs unwrapped to one physical line). Bilingual scope stays the PRFC tree only; the wider corpus pairs on a trigger signal — documentation routinely authored in Chinese — and gets its own record then. `README_xh.md` keeps its name until that day.

## Alternatives considered

**Port the reference documentation pipeline — a TS/mdast doc-typecheck, i18n manifests, word budgets over all documents, a dependency-graph gate scheduler.** It lost: no Node toolchain at the repo root, a corpus of dozens of files rather than hundreds; stdlib gates finish in seconds, and prek plus `check_drift.py` are already the established aggregation pattern here.

**Rules without gates.** It lost: undisciplined drift is the exact failure the gates exist for; every rule in the standard names the gate that enforces it — a rule without machinery re-creates the failure it prohibits.

**Fold the gates into `check_drift.py`.** It lost: that script's contract is non-destructive regenerate-and-diff over generated artifacts; prose linting is neither regenerating nor diffing. One aggregator per class, with CI calling both identically.

**Gate `specs/redesign/` with the current-state check as proposed.** It lost at implementation time: the scan surfaced that the specs' hits are comparative design language ("bleach 已废弃, nh3 是替代", "换 aiohttp, requests 不再用"), not stale narration — the redesign corpus narrates transitions by contract, and forcing rewording would churn edit-gated design docs for near-zero value. The scope adaptation is recorded above rather than papering over the proposal's wording.

**Go fully bilingual now.** It lost: roughly thirty-five files of one-time translation plus a permanent pairing duty, eighteen of them the edit-gated specs — translating is editing; the reference adopted pairing in two steps on a trigger, and this records the same order.

**Keep the global `^\.agents/` exclude.** It lost: the tree lands ungated and the format gate passes green over zero files — enforcement parity is the reason a gate exists.

## Consequences

`doc_sync` runs green over the full corpus (63 files checked by links and wrap, 15 by current-state, 8 PRFC files by format, 4 budgets); each gate was drilled on a hand-made specimen — dead link, reflowed paragraph, history narration, malformed record, non-conventional commit subject — failing before the fix and passing after. The normalization unwrapped fourteen files mechanically; a first one-shot reflow script differed from the gate's masking (it ate the backticks that mark inline code, and it joined YAML frontmatter lines in a SKILL.md) — the fix was to re-derive the reflow from the gate's own masking functions and restore the file from the then-clean mirror, which is the working proof that throwaway tooling must import the gate's logic rather than approximate it. The costs accepted: full-corpus truth lives in CI while the local hook checks staged files only (the same trade the reference recorded); a current-state false positive is remedied by per-file exemption in the gate's scope list with the reason recorded; and `.agents/skills/` prose is gated by CI full runs only, since the global exclude that protects the mirror from mutating hooks also keeps it out of staged doc runs.
