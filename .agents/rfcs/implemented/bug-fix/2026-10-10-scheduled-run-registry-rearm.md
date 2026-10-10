# RFC: scheduled-run re-arms on registry membership changes

Status: implemented

English | [中文](2026-10-10-scheduled-run-registry-rearm.zh.md)

## Problem

The per-integration schedule overrides feature ([2026-10-08](../feature/2026-10-08-per-integration-schedule-overrides.md)) moved schedule-group resolution into the `scheduled-run` row's apply, snapshotting `ctx.integrations.names` at arm time. But integration instances mount as child fibers of the `integrations` row, and the kernel settles in passes: pass 1 applies sibling rows — the `integrations` row provides an empty registry and mounts its children as PENDING — and only pass 2 loads those children, which is when instances actually join the registry. The sibling `scheduled-run` row applies in pass 1, so its snapshot is structurally empty at first boot. Deployed to staging on 2026-10-08 22:59, this armed `30 8,22 * * * -> (none)` and every subsequent scheduled run executed zero integrations for two days (issue [#36](https://github.com/jukanntenn/progress/issues/36)). The pre-override code armed `every(cron, runner.run_once)` — membership resolved at fire time — so mount order had never been load-bearing, and the shipped tests boot trees with a pre-populated static registry (no child fibers), which is why the two-pass shape was never exercised.

The same incident exposed a second defect: a zero-integration run completes with `exit_code=0`, so `progress.pipeline.last_success_epoch` keeps refreshing and the Uptime Kuma push reports `status=up`. The "pipeline silent" alert measures success staleness, and an empty run is a success — this failure class is invisible to every shipped alert by construction.

## Decision

### Registry membership is an event

The `@register` shim emits `integration/registry-changed` (an `emit`-mode catalog event carrying the post-change member names) after every instance add and remove. Membership changes were already implicit in the tree — boot pass 2, L3 plugin installs, integration fiber restarts — but nothing observed them; now the pipeline has one notification point for all three.

### Arming is re-entrant, not one-shot

The `scheduled-run` row's apply builds its schedule groups inside `_rearm()`: dispose the current scheduler entries, re-resolve overrides from live DB sections, re-group the live registry, arm fresh entries. It runs once at apply and again on every `integration/registry-changed`, serialized by a lock (boot emits once per child fiber; each re-arm reads current state, so the sequence converges regardless of count). The observable gauges read a mutable arm-state holder instead of apply-time closures, so re-arms are visible without re-registering instruments; `last_success` survives across re-arms. A closed flag set by the fiber's teardown makes late events during tree unwind no-ops. Arming correctness no longer depends on settle-pass ordering at all.

### The coverage invariant pages instead of silently succeeding

Every fire checks that each mounted integration belongs to some armed group. A mounted-but-unscheduled integration means the schedule drifted from the registry; the run is then reported as failed — Kuma `status=down`, no `last_success` refresh, an ERROR log line, and a `progress.schedule.coverage_drift` business event — even though `RunOutcome.exit_code` itself is unchanged. This is deliberately computed from live state rather than trusting the armed groups, so it would have flagged the original regression on its first fire and flags any future drift (a lost re-arm, a schedule shaped by a broken fiber) within one expected-gap window instead of never.

### The boot window fails loud, not silently

Between the pass-1 arm and the pass-2 re-arm the armed groups may be empty while integrations mount; a cron fire landing in that window trips the coverage invariant and reports failure rather than succeeding over nothing. Fires are hours apart and the window is milliseconds; no catch-up is already the scheduler's documented semantics.

## Testing

`tests/component/test_scheduled_run_arming.py` boots the real shim tree — child fibers, the real two-pass settle, the real scheduler and scheduled-run rows — waits for the re-arm, fires the armed trigger directly, and asserts the mounted integrations actually run; it fails against the pre-fix source. `tests/unit/runtime/test_scheduled_run.py` adds the re-arm on an emitted event (fire runs the newly mounted integration), the drift verdict (mounted-but-unscheduled ⇒ `coverage_drift` business event, Kuma push `success=False`), and the no-drift verdict (`success=True`).

## Alternatives considered

**Resolve membership lazily at fire time.** Per-fire resolution fixes the global group but not the entry set: integrations whose overrides shape separate scheduler entries would still be missing entries armed from an empty registry, so overrides would silently not run — the same bug one level up.

**Await child readiness inside the row's apply.** The kernel exposes no "tree settled" hook a sibling can await, and a registry that is legitimately empty (no integrations configured) would make any wait-for-population loop hang the boot.

**Apply child fibers synchronously inside the parent's load.** Changing kernel mount semantics for one consumer inverts the settle model the whole composition system is built on; the defect is in the consumer's assumption, not the kernel.

**Treat zero-integration runs as failures unconditionally.** A deployment where every integration overrides off the global cron legitimately arms an empty global group (the pre-override idle-cron behavior the feature RFC preserves); failing those runs would cry wolf. The coverage invariant is the precise form: fail only when mounted integrations are scheduled nowhere.

## Consequences

- Schedule groups are correct regardless of mount timing, and live registry changes — L3 plugin installs, integration fiber restarts, recompose — now re-shape the schedule without waiting for an L0 reload. The feature RFC's hot-update section was updated to record this.
- Boot performs one re-arm per integration child (serialized, DB-light, milliseconds each); the last one wins and reads full state, so intermediate shapes are never observable to a fire that matters.
- A drift verdict flips the Kuma push and `last_success` but not `RunOutcome.exit_code`, so run-level failure metrics do not see it; a dedicated Grafana alert on `progress.schedule.coverage_drift` is deferred to the infra-side rule file, as the monitoring runbook defers all rule wiring.
- The `scheduled-run armed: <cron> -> <members>` log line is now pinned by a test as an operational triage surface — it is the first place incident analysis looks (it was, for #36), so format changes must now update the component test.
