# RFC: Per-integration schedule overrides

Status: proposed

English | [中文](2026-10-08-per-integration-schedule-overrides.zh.md)

## Problem

Scheduling is one global cadence. `core.schedule.cron` arms a single `scheduled-run` trigger that fires `runner.run_once()` over every mounted integration together, so the finest cadence the settings UI can express is "the whole pipeline, N times a day" — an integration whose data naturally moves faster (feed polling) or slower (repo release sync) cannot get its own rhythm without dragging everything else along. This gap was already named when the in-process scheduler landed — no integration can declare its own cadence, feed polling faster than repo sync was impossible to express — and the pieces shipped to close it are all in place (the per-entry `every(cron, fn)` scheduler, the L0 reload that restarts the scheduled-run fiber, the schema-driven settings editor that renders any plugin config field for free); only the per-integration granularity itself is missing. The concrete driver: `feed` runs twice a day with everything else and should run every four hours.

## Proposal

### The capability is a convention config field

An integration declares schedule capability by declaring a `schedule_cron: str = ""` field on its own `config_schema` model — nothing else. Presence of the field in `model_fields` *is* the capability: the settings editor renders it automatically from the section schema, `PUT /api/v1/config/{section}` validates and stores it in the integration's own DB section, and a schema that never declared the field rejects the key on write (`extra="forbid"`), so an undeclared integration inherits the global cadence with zero code and cannot drift into a half-configured state. The five-hook `Integration` protocol is untouched: third-party integrations load unchanged, and opting in is one field in the integration's own config model — the self-contained autonomy the plugin layout already promises.

### Unified cron validation

One shared, croniter-backed validator owns the field's semantics for every plugin schema — a reusable pydantic annotated type accepting the 5-field cron dialect the scheduler and `expected_max_gap_seconds` already parse. Every integration that declares the field gets identical validation: an invalid expression returns 422 at PUT and leaves the DB untouched; an invalid value already in the DB (schema downgrade, hand edit) degrades at load to inherit-global with a logged warning, the same graceful-degradation idiom `strip_unknown_config_keys` and the feed config loader already follow.

### Override means independent cadence

At arm time the `scheduled-run` row resolves every mounted integration's effective cron — its `schedule_cron` override if non-empty, else the global `schedule.cron` — groups integrations by effective cron, and registers one scheduler entry per group firing `run_once(only=<group>)`. An overridden integration leaves the global group entirely: no second ride on the global cron, no duplicate reports or notifications, and the group's cadence is the integration's cadence. Section reads happen inside the fiber's `apply` (async DB reads), so every re-arm re-reads live config, and a corrupt or missing section degrades to inherit-global for that integration.

### The runner runs subsets

`run_once()` gains an optional `only: set[str]` filter over the producer list. Event payloads, report assembly, and notification authoring already stream per integration, so a subset run is exactly today's full run minus the excluded integrations — no new pipeline path. The on-demand `progress run` stays unfiltered: a manual run means "run everything now", and `trackers_only` keeps its existing meaning.

### Hot update rides L0

No new reload machinery. The `scheduled-run` row already injects `config`, so any section PUT (global or plugin) triggers `composer.reload_config()`, which restarts the fiber; the restart re-reads every section and re-arms the groups. Editing `feed.schedule_cron` in the settings UI takes effect on the next arm without a process restart, exactly as editing the global cron does today.

### Observability per schedule

`progress.schedule.expected_max_gap_seconds` and `progress.pipeline.last_success_epoch` gain a schedule-group attribute (the group's cron and member names), and the Uptime Kuma push fires per group with that group's retention — the most frequent group naturally dominates the single push monitor's silence window. Alert rules that today divide by the unattributed gauge switch to group-aware queries in the same change.

### feed is the first adopter

`FeedIntegrationConfig` declares `schedule_cron` with the example `0 */4 * * *`; every other shipped integration declares nothing and keeps the global cadence.

## Alternatives considered

**A protocol-level capability attribute (`supports_schedule = True` on the Integration class).** The override value must live in a config model anyway — that is the surface the settings editor renders, validates, and stores — so an attribute adds a second source of truth for one bit while the field alone carries the whole capability.

**Overridden integrations also ride the global cron.** Double scheduling produces duplicate reports and notifications on every overlap and defeats the point of a separate cadence; exclusion is the only semantics that keeps one integration on exactly one schedule.

**Each integration registers its own `every(cron, ...)` inside `setup`.** Scheduling ownership disperses into per-integration code with no single place that sees every cadence — the global-excludes-overridden grouping, the per-group observability, and the reload re-arm all need one consumer that resolves the full map at arm time.

**A central per-integration schedule map in core config.** Core would have to know plugin names and their schema fields, violating the model where each integration owns its own config section and schema, and hiding the capability from the per-integration settings surface the schema editor already renders.

**Multiple global crons (`schedule.crons`).** Still pipeline-wide: it expresses "run everything more often", not "run feed faster than repo sync".

**Per-plugin cron dialects.** Each plugin writing its own validation diverges on what a valid expression is; one shared validator keeps PUT errors and load-time degradation uniform.

## Acceptance criteria

- feed with no `schedule_cron` value: unchanged behavior — every global-cron run includes feed with every other integration.
- feed with `schedule_cron = "0 */4 * * *"`: a dedicated schedule fires every four hours running only feed; global-cron runs exclude feed.
- The settings UI renders the schedule field in the feed section from the section schema alone; an invalid cron returns 422 on PUT and leaves the DB untouched.
- Changing `schedule.cron` or `feed.schedule_cron` through the API re-arms the schedules without a process restart (L0 reload).
- The cadence gauges export per group; alert rules query by the group attribute.
- An integration whose schema lacks the field inherits the global cadence; PUTting the key into such a section fails validation.

## Risks

- Observability migration is coupled: the two cadence gauges become attributed series, and the same change must update the dashboards and alert rules that query the unattributed ones — shipped days ago with the production monitoring — or alerts silently stop matching.
- Arm-time section reads make the scheduled-run fiber depend on DB state at (re)arm; a corrupt section degrades to inherit-global with a logged warning rather than failing the fiber.
- The L0 re-arm window briefly has no schedules between dispose and arm — the same exposure a global-cron edit has today, bounded by the fiber restart.
- One shared Kuma push URL across groups lets the most frequent group mask a silently-stalled slower group; a per-group monitor needs per-group env configuration and is deferred.
- The schema-driven editor renders cron as free text with validation as the only guardrail; a dedicated cron widget can come later without touching this contract.
