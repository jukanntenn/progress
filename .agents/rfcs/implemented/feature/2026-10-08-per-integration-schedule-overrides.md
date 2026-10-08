# RFC: Per-integration schedule overrides

Status: implemented

English | [中文](2026-10-08-per-integration-schedule-overrides.zh.md)

## Problem

Scheduling is one global cadence. `core.schedule.cron` arms a single `scheduled-run` trigger that fires `runner.run_once()` over every mounted integration together, so the finest cadence the settings UI can express is "the whole pipeline, N times a day" — an integration whose data naturally moves faster (feed polling) or slower (repo release sync) cannot get its own rhythm without dragging everything else along. This gap was already named when the in-process scheduler landed — no integration can declare its own cadence, feed polling faster than repo sync was impossible to express — and the pieces shipped to close it were all in place (the per-entry `every(cron, fn)` scheduler, the L0 reload that restarts the scheduled-run fiber, the schema-driven settings editor that renders any plugin config field for free); only the per-integration granularity itself was missing. The concrete driver: `feed` runs twice a day with everything else and should run every four hours.

## Decision

### The capability is a convention config field

An integration declares schedule capability by declaring a `schedule_cron: str = ""` field on its own `config_schema` model — nothing else. Presence of the field in `model_fields` *is* the capability: the settings editor renders it automatically from the section schema, `PUT /api/v1/config/{section}` validates and stores it in the integration's own DB section, and a schema that never declared the field rejects the key on write (`extra="forbid"`), so an undeclared integration inherits the global cadence with zero code and cannot drift into a half-configured state. The five-hook `Integration` protocol is untouched: third-party integrations load unchanged, and opting in is one field in the integration's own config model — the self-contained autonomy the plugin layout already promises.

### Unified cron validation

`progress.utils.cron` owns the field's semantics for every plugin schema: `CronExpression`, a reusable pydantic annotated type accepting the 5-field cron dialect the scheduler and `expected_max_gap_seconds` already parse (empty inherits; six-field seconds forms are rejected). Every integration that declares the field gets identical validation: an invalid expression returns 422 at PUT and leaves the DB untouched; an invalid value already in the DB (schema downgrade, hand edit) degrades at arm time to inherit-global with a logged warning, the same graceful-degradation idiom `strip_unknown_config_keys` and the feed config loader already follow.

### Override means independent cadence

At arm time the `scheduled-run` row resolves every mounted integration's effective cron — its `schedule_cron` override if non-empty, else the global `schedule.cron` — groups integrations by effective cron (`resolve_schedule_groups`), and registers one scheduler entry per group firing `run_once(only=<group>)`. An overridden integration leaves the global group entirely: no second ride on the global cron, no duplicate reports or notifications, and the group's cadence is the integration's cadence; an override equal to the global expression joins the global group instead of duplicating it. Section reads happen inside the fiber's `apply` (async DB reads), so every re-arm re-reads live config, and a corrupt or missing section degrades to inherit-global for that integration. The global group is armed whenever the global cron is set, even with no members, preserving the pre-override idle-cron behaviour.

### The runner runs subsets

`run_once()` takes an optional `only` filter over the producer list; unknown names in the filter log a warning and are ignored. Event payloads, report assembly, and notification authoring already stream per integration, so a subset run is exactly the full run minus the excluded integrations — no new pipeline path. The on-demand `progress run` stays unfiltered: a manual run means "run everything now", and `trackers_only` keeps its existing meaning.

### Hot update rides L0

No new reload machinery. The `scheduled-run` row already injects `config`, so any section PUT (global or plugin) triggers `composer.reload_config()`, which restarts the fiber; the restart re-reads every section and re-arms the groups. Editing `feed.schedule_cron` in the settings UI takes effect on the next arm without a process restart, exactly as editing the global cron does.

### Observability per schedule

`progress.schedule.expected_max_gap_seconds` and `progress.pipeline.last_success_epoch` export one observation per schedule group with the group's cron and member names as attributes, and the Uptime Kuma push fires per group with that group's retention — the most frequent group naturally dominates the single push monitor's silence window.

### feed is the first adopter

`FeedIntegrationConfig` declares `schedule_cron` with the example `0 */4 * * *`; every other shipped integration declares nothing and keeps the global cadence.

## Testing

`tests/unit/test_cron_validator.py` pins the dialect: empty passes, five-field expressions pass, four- and six-field forms, out-of-range minutes, and garbage raise, and the annotated type rejects inside a model. `tests/unit/runtime/test_scheduled_run.py` pins the grouping: the pure `resolve_schedule_groups` (global group membership, override exclusion, same-expression merge, empty-global no-groups and override-only), boot-level arming (idle row, global cron, env fallback, override arms a separate `scheduled-run[<cron>]` entry while the global entry drops the integration, override-equal-global joins, invalid stored value degrades), and the pre-existing cadence math and kuma URL builders. `tests/component/test_core_orchestration.py` pins the runner subset (`only` runs just the named integration; unknown names are ignored), and `tests/component/test_config.py` pins the write path (invalid cron on `PUT /api/v1/config/feed` returns 422 and stores nothing; a valid cron round-trips through the section).

## Alternatives considered

**A protocol-level capability attribute (`supports_schedule = True` on the Integration class).** The override value must live in a config model anyway — that is the surface the settings editor renders, validates, and stores — so an attribute adds a second source of truth for one bit while the field alone carries the whole capability.

**Overridden integrations also ride the global cron.** Double scheduling produces duplicate reports and notifications on every overlap and defeats the point of a separate cadence; exclusion is the only semantics that keeps one integration on exactly one schedule.

**Each integration registers its own `every(cron, ...)` inside `setup`.** Scheduling ownership disperses into per-integration code with no single place that sees every cadence — the global-excludes-overridden grouping, the per-group observability, and the reload re-arm all need one consumer that resolves the full map at arm time.

**A central per-integration schedule map in core config.** Core would have to know plugin names and their schema fields, violating the model where each integration owns its own config section and schema, and hiding the capability from the per-integration settings surface the schema editor already renders.

**Multiple global crons (`schedule.crons`).** Still pipeline-wide: it expresses "run everything more often", not "run feed faster than repo sync".

**Per-plugin cron dialects.** Each plugin writing its own validation diverges on what a valid expression is; one shared validator keeps PUT errors and load-time degradation uniform.

## Consequences

- An integration that declares `schedule_cron` gets its own cadence with zero frontend work: the settings editor renders the field from the section schema, and the write path validates, stores, and re-arms live. `feed` runs every four hours while the rest of the pipeline keeps the global rhythm.
- The two cadence gauges are attributed series now; dashboards and alert rules must query by the `schedule`/`integrations` attributes instead of assuming one unattributed pipeline cadence — the observability documentation was updated in the same change, and pre-existing alert rules that divided by the unattributed gauge need the attribute filter added when they are next touched.
- Arm-time section reads make the scheduled-run fiber depend on DB state at (re)arm; a corrupt section degrades to inherit-global with a logged warning rather than failing the fiber.
- The L0 re-arm window briefly has no schedules between dispose and arm — the same exposure a global-cron edit already had, bounded by the fiber restart.
- One shared Kuma push URL across groups lets the most frequent group mask a silently-stalled slower group; a per-group monitor needs per-group env configuration and stays deferred.
- The schema-driven editor renders cron as free text with validation as the only guardrail; a dedicated cron widget can come later without touching this contract.
