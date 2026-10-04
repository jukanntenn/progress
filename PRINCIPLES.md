# Coding principles

Behavioral constraints for the agent. Each is a rule the agent gets wrong without being told. Production safety and data integrity outrank every principle here — including the license to redesign from scratch; against a mere default or style rule, the principle wins.

## Ground every conclusion in fact

Library facts, APIs, and protocols must be read from source or docs before you act on them — training data is a blind spot, not a source. Verify every conclusion on the ground: `file:line` for logic, a headless DOM (playwright) for UI, read-only commands in prod, with means the model can actually perform (no screenshot analysis). Pure algorithm or syntax knowledge may use training knowledge.

The fn outage is the shape of getting this wrong: `schemaAdapter` mapped `type:object` to an object list from a guess, and broke production config.

## Defer to community convention

When a convention or best practice is uncertain, ask "what is the community/official convention?" and verify against authoritative open-source source, not training memory (e.g. whether `format`/`lint` are the prek group names, or which generated files to exempt from formatting).

Distinct from *Ground every conclusion in fact*: that one governs facts about a library you are integrating; this one governs convention and best-practice decisions.

## Converge before you implement

A spec or plan must be self-contained, complete, and unambiguous — an executor with no taste can land it mechanically, with no room to improvise. Resolve every open point before implementing; do not start on the strength of a half-settled plan.

## Fix the root cause, not the symptom

The solution you choose must be the most natural and optimal — not a patch over the symptom, and not one trapped by the existing implementation. You may shed all legacy and start from zero when the root fix requires it.

When hook coverage leaked, the fix was not to patch each agent's extension map but to delegate to `prek.toml` as the single truth.

## Design from first principles

Derive a design from the business essence; every premise is breakable; an elegant scheme beats an inherited one. Distinct from *Fix the root cause, not the symptom*: that one is how you *fix* a problem (root, not patch); this one is how you *design* a system (re-derive, question assumptions).

## Single source of truth

Each category of information — config, i18n, integration names, hook definitions — has exactly one authoritative source. The frontend renders; it does not decide.

Integration names come from the backend JSON schema, not from hardcoded frontend translations.

## Naming is part of the API

A name is an API surface. If a name does not fit its business meaning, do not force it — brainstorm candidates and let the user choose, to prevent semantic drift (e.g. `Check` → `run`).

## Degrade gracefully, never silently

A failure must be handled and observably recorded, and must not block downstream work — but a silent failure is always wrong. The fn outage is the cautionary shape: CoreConfig validation failed, fell back to defaults with no signal, and the whole service degraded with no one knowing.

## Minimal mock, maximal real

Mock only the request boundary, never the whole service. e2e drives real containers and real tmp SQLite; local and CI run the same suite as fully as feasible; coverage is standard, not optional.
