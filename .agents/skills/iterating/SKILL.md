---
name: iterating
description: Iterate the user's input into a delivered artifact — explore the project and reference repos, discuss and decide each point with them grounded in fact, then land the decisions as a spec or an implementation. Use when the user wants to take a request all the way to a finished spec or code through grounded discussion, or passes requirements to work through together.
argument-hint: "Requirements or design points to discuss"
---

The operational form of the project's PRINCIPLES — ground in fact, defer to community, first principles, fix the root; read PRINCIPLES.md for the values, what follows is the how.

The user's input — the request that triggered this skill, or the text passed with it — is the work to move through.

**Explore** before you propose. Read the project — the relevant existing code and tests, and how a similar feature is already done here — and reuse the dependencies and commands that already exist. For any library, API, or protocol you'll lean on, prefer its live source and docs over training data: look in `.local/contexts` and `~/Workspace/contexts`; if a repo is missing, `gh repo clone {owner}/{repo}` into `.local/contexts` at the version the project depends on, and show evidence it's actively maintained. List your references and let the user add to them before you rely on them; if a clone fails and that repo would beat training data, stop and ask the user to set it up.

**Regroup** the user's input into the agenda — do not take the list as given. Merge related items into coherent themes, and order them so each theme's prerequisites come first: an earlier theme must never depend on a decision still pending in a later one. Show the user this regrouped, ordered agenda before you walk it.

**Discuss** one theme at a time. Before raising any question on a theme, report the relevant code's current state; brainstorm options from first principles — shedding legacy and redesigning from zero when the root fix requires it; then decide the best option yourself when you can, and put it to the user (ask-user-questions) only when you cannot. **Confirm** before moving on: advance to the next theme only after the user explicitly confirms this one, and stay on the current theme until then.

**Land** only after the user has confirmed every theme: produce what was agreed — a spec, the implementation, or both. Discussion and production are separate phases; don't produce theme-by-theme as each settles. If the output is a spec, state the terminal design — no "was X, now Y" evolutionary prose.

## Variants

- **Spec landing or refactor** (no requirement discussion): replace the discussion with a pre-landing assessment — judge the spec for implementability, contradictions, ambiguities, or anything unbuildable; propose remedies and reach consensus first. Acceptance bar: old code fully cleared, normal and error cases exhaustively tested, UI verified with playwright-cli and screenshots.
- **Review**: report only opinions you hold with certainty; hold the rest. Do not adopt a suggestion without verifying it — some designs are intentional, and reviewers err.
