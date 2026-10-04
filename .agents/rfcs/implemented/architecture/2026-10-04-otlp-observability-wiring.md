# RFC: OTLP observability wiring — three signals, environment identity, and the file fallback

Status: implemented

English | [中文](2026-10-04-otlp-observability-wiring.zh.md)

## Problem

Progress ran file-mode observability only: traces/metrics as local JSONL, logs in a rotating file, errors in Bugsink. Nothing reached the externally deployed observability stack (Jaeger / VictoriaMetrics / VictoriaLogs / Grafana behind one otelcol-contrib), so the project had no dashboards, no alerting, and no availability monitoring — while the sibling project markpost had already built and battle-tested exactly that pattern on the same infrastructure. Three gaps blocked a copy: the deployment.environment.name resource attribute was effectively hardcoded to `production` (staging would mislabel itself, and the SDK's explicit-attrs-beat-env semantics meant the standard env vars could not fix it), the OTel logs signal was absent (spec 04 had rejected it as immature — leaving Grafana's logs pillar empty for this service), and the metrics stream had no always-on series (business counters only tick when the pipeline runs, twice a day), so any "telemetry gap" alert would fire on idle silence rather than a broken path. Separately, a cadence assumption lurked in every obvious alert design: "twice a day" is a runtime config knob, not a property of the system.

## Decision

**Producer side (this repository).** The dual-mode exporter design is kept and extended to all three signals: `OTEL_EXPORTER_OTLP_ENDPOINT` set → OTLP HTTP (the SDK natively reads `OTEL_EXPORTER_OTLP_HEADERS` / `OTEL_EXPORTER_OTLP_COMPRESSION`, so auth and gzip are deployment env vars, zero code); unset → file exporters, unchanged. Logs ship via a new `OtelLogHandler` — a stdlib handler on the root logger (handler semantics give exactly-once forwarding per record regardless of how many ProcessorFormatter sinks format it later), mapping level→severity, the event name→body, remaining scalar fields→attributes, and attaching live trace context through `emit(context=get_current())`. INFO+ ships; DEBUG stays file-only; the rotating `progress.log` is dual-written in every mode as the crash channel. Spec 04's rejection of the logs signal is amended: the pinned opentelemetry-sdk 1.44 ships logs in the same packages as traces/metrics (zero new dependencies), and the same bridge is production-proven on this stack by markpost.

**Environment identity.** `effective_environment()` resolves `deployment.environment.name` from the standard `OTEL_RESOURCE_ATTRIBUTES` first, config default second; `_build_resource` applies the same precedence for `OTEL_SERVICE_NAME`. The resolved value feeds the OTel resource and the Bugsink `environment` tag from one call, so the two backends can never label one deploy differently. (The naive `Resource.create({}).merge(...)` approach is wrong: the env detector fabricates `service.name="unknown_service"` when the variable is unset, which would override the explicit constant — the resolver parses the two env vars directly instead.)

**Always-on runtime metrics.** `opentelemetry-instrumentation-system-metrics` (with psutil) instruments the process at setup; `process.memory.usage` and friends are the anchor series the telemetry-gap alert watches, and the Runtime dashboard's panel data.

**Cadence-agnostic scheduling observability.** The scheduled-run entry exports `progress.schedule.expected_max_gap_seconds` (largest gap between the next consecutive cron fires, computed at arm time) and `progress.pipeline.last_success_epoch` (set on each success). Alert windows divide by the exported gap, so changing `schedule.cron` — a Web-UI runtime knob — retunes alerting without touching provisioned rules. The same gap drives the Uptime Kuma push heartbeat: after every run the scheduler pushes a verdict (`status=up|down`, message, `ping` retention = 2× gap + 30m, capped at kuma's 24h per-push limit) to `PROGRESS_KUMA_PUSH_URL`; the push is best-effort (failed pushes logged and swallowed — kuma's silence detection is the backstop), and an empty URL disables it.

**Deployment wiring.** The Ansible compose template injects the OTLP block only when `progress_otlp_endpoint` and `progress_otlp_token` are both defined (either missing → file mode, the deployment-level degradation path), plus `PROGRESS_OBSERVABILITY__BUGSINK__DSN` (closing a documented-but-missing wiring) and `PROGRESS_KUMA_PUSH_URL`. Token and push URL are vault secrets; the endpoint is plain group_vars. The infrastructure side (collector token admission, Grafana provisioning — a `progress` folder with four dashboards, eleven alert rules, a `progress-alerts` contact point and routing policy, kuma group + three staging leaves) is handoff material on the observability NAS, recorded in `docs/monitoring.md`.

**Staging-first rollout.** Production runs the pre-refactor build during staging-vs-production comparison validation and must not be touched: the collector admits a production token that nothing uses, the production telemetry-gap rule and kuma group are deferred to promotion day (provisioning them now would fire permanently against a build that never emits), and everything else is env-dimensional multi-instance rules that stay silent for environments with no series.

## Alternatives considered

**Host-side log shipping (promtail/alloy tailing `progress.log`).** It lost: two extra moving parts per host, log-rotation races, and a second telemetry transport to operate — against a dual-write bridge that reuses the already-pinned SDK and the pattern proven next door.

**A config-schema `[observability.otel]` section.** It lost: the SDK already owns the standard env-var surface, markpost set the deployment-only precedent, and a schema change drags OpenAPI/frontend/migration surface for zero added capability. The spec 04 sketch of that section was already demoted to code constants before this RFC.

**Per-environment dashboard copies.** It lost to the single-set-with-`env`-variable pattern for the reason markpost recorded when it overhauled its own wiring: copies drift silently, and multi-dimensional alert rules yield per-env instances natively.

**A shared token for both environments.** It lost to per-env tokens: blast-radius isolation and independent revocation (staging leakage must not force a production token rotation).

**Hardcoded cadence in alerts ("no run in 14h").** It lost: `schedule.cron` is a Web-UI runtime knob; the app exporting its own expected gap keeps provisioned rules correct across cadence changes and is the mechanism this RFC ships.

**Extending the `bearertokenauth` rename on the shared collector now.** Deferred, not lost: the front door is shared with markpost production; the rename is cosmetic and rides the promotion-day change instead of adding churn to a hot path for aesthetics.

## Consequences

Staging telemetry is visible in Grafana as `deployment.environment.name=staging` (previously impossible — the label was hardcoded), logs/traces/metrics cross-navigate via the native trace context, and both a Grafana rule and a kuma push heartbeat watch the pipeline independently — the alert layer inherits the same degradation philosophy as the transport layer (each path assumes the other may be down; the local files assume both are). The costs accepted: remote DEBUG logs are given up deliberately (file-only), traces/metrics during a collector outage are lost after the SDK's retry budget (the app log file remains the incident evidence — markpost's accepted trade, now ours), the ERROR-log-rate rule ships paused behind a datasource wart rather than worked around blind, and the infra-side provisioning (NAS files, kuma monitors) lives outside this repository's gates — `docs/monitoring.md` is the sync point, which is exactly how the sibling project operates its stack. Cadence-sensitive behavior (silent-run alerting, heartbeat retention) is now a contract between the app's exported gauges and provisioned rules; any future scheduler change must keep exporting the expected-gap gauge or the alerts degrade to no-data silence — the telemetry-gap rule watches that failure mode too, since the gauges ride the same always-on metric stream.
