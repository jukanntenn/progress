# Observability

English | [中文](observability.zh.md)

Progress ships three complementary observability channels:

- **OpenTelemetry** owns **traces**, **metrics**, and **logs**. Default mode writes traces/metrics as JSON-Lines files to `<state_home>/observability/` (`traces.jsonl` / `metrics.jsonl`) while logs go to the rotating `<state_home>/logs/progress.log`. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship all three signals to an OTLP collector instead (see `docs/observability-deploy.md`); in that mode logs are dual-written — INFO+ also go remote, the file stays as the crash channel.
- **Bugsink** (a self-hosted, Sentry-compatible server) receives **errors and crashes** only, via `sentry-sdk`. It does not ingest traces/metrics/sessions.
- **Availability monitoring** (Uptime Kuma probes + a run-outcome push heartbeat) is a separate layer, documented in `docs/monitoring.md`.

OTel signals are **always on** (sampling rate = 1.0, code constants per spec 04) — there is no `[observability.otel]` config section or `enabled` toggle. Bugsink is opt-in: configured via the DB-stored `[core.observability.bugsink]` section or the `PROGRESS_OBSERVABILITY__BUGSINK__*` environment variables, and disabled when the DSN is empty.

## Environment identity

`deployment.environment.name` resolves once per boot: the standard `OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=<env>` (and `OTEL_SERVICE_NAME`) environment variables win over the config default (`core.observability.bugsink.environment`, `"production"`). The resolved value feeds both the OTel resource and the Bugsink `environment` tag, so Grafana and Bugsink can never label one deploy differently. Container deploys inject identity via environment variables only — no config-schema changes.

## OTLP mode (remote telemetry)

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://<otel-collector>:4318
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<token>
OTEL_EXPORTER_OTLP_COMPRESSION=gzip
OTEL_SERVICE_NAME=progress
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=staging
```

(Variables above are read natively by the OTel SDK; the Ansible compose template injects the block only when endpoint+token are both defined — either missing means file mode, which is the deployment-level degradation path.)

With the endpoint set:

- **Traces/metrics** export over OTLP HTTP (60-second metric cadence, batched spans). No local JSONL is written.
- **Logs** are bridged by `OtelLogHandler`: a stdlib handler that forwards each record exactly once — severity from the level, the event name as body, remaining scalar fields as attributes, live trace context attached natively (VictoriaLogs exposes `trace_id` as the Jaeger link field). DEBUG stays file-only; the rotating file keeps everything, collector outage or not.
- **Runtime metrics** from `opentelemetry-instrumentation-system-metrics` (process memory/CPU/threads, system gauges) provide an always-on anchor series — the "telemetry gap" alert watches it to catch a broken app→collector→store path.
- **Scheduler gauges** export the run cadence: `progress.schedule.expected_max_gap_seconds` (computed from the cron at arm time) and `progress.pipeline.last_success_epoch`. Alert windows divide by the exported gap, so changing `schedule.cron` retunes alerting automatically — no assumed run counts.
- `PROGRESS_KUMA_PUSH_URL` (optional) makes the in-process scheduler push each run's verdict to an Uptime Kuma push monitor, with a per-push retention derived from the expected gap. Empty → no push; a failed push is logged and swallowed (kuma's silence detection is the backstop).

## File mode (default / fallback)

Bugsink is a Web-class config field (DB `config` table, `section="core"`):

```toml
[core.observability.bugsink]
dsn = "http://<public-key>@<host>:<port>/<project-id>"  # empty → disabled + warning
environment = "production"
```

Environment overrides (used by Docker / `docker-compose`):

```
PROGRESS_OBSERVABILITY__BUGSINK__DSN=http://<key>@192.168.5.50:8770/<project-id>
PROGRESS_OBSERVABILITY__BUGSINK__ENVIRONMENT=production
```

## Where telemetry comes from

`setup_observability()` is called once per process — from the CLI `run` command (`component="cli"`) and from the FastAPI app (`component="api"`).

- **Auto-instrumented:** FastAPI requests (API only), SQLite (covers tortoise), outbound `aiohttp` HTTP calls (covers gidgethub), and stdlib `logging` (trace ids injected into records).
- **Manual spans:** `progress.run` / `progress.check` (the run root), `progress.integration.<name>` (per integration), `progress.git.op` (each git subprocess), `progress.ai.call` (AI extraction), `progress.changelog.parse`.
- **Business events** (`record_business_event`): `progress.run.started`, `progress.run.completed`, `progress.integration.run`, `progress.repos.checked`, `progress.git.diff_decided`, `progress.git.diff_failed`, `progress.releases.truncated`, `progress.changelog.sync`, `progress.markpost.published`, and more.

Cross-signal correlation relies on the OTel `trace_id` (no explicit run_id): every span in one `core.run()` shares the same trace, and `structlog` injects `trace_id`/`span_id` into each log record so logs join traces seamlessly.

## Output format

### `traces.jsonl`

Standard OTLP JSON-file format — one resource-spans object per export flush. Each `scopeSpans[].spans[]` entry is a span with `name`, `traceId`, `spanId`, `parentSpanId`, `startTimeUnixNano`, `endTimeUnixNano`, `attributes`, and `status`. A span with no `parentSpanId` is a trace root.

### `metrics.jsonl`

Standard OTLP JSON-file format — `resourceMetrics[].scopeMetrics[].metrics[]`, each metric with `name` and `sum`/`histogram` data points carrying values and attributes (e.g. `{"status":"success"}`, `{"repo":"foo/bar"}`). Exported every 60 seconds by the periodic metric reader, plus a final flush on shutdown.

## Querying with jq

```bash
# Every span, trimmed to the essentials
jq -c '.resourceSpans[].scopeSpans[].spans[] | {name, trace: .traceId, span: .spanId, parent: .parentSpanId}' data/observability/traces.jsonl

# Reconstruct one trace by id
jq -c '.resourceSpans[].scopeSpans[].spans[] | select(.traceId=="d43854b45b94ab91fee0463fe92a72c7")' data/observability/traces.jsonl

# Failed git ops
jq -c '.resourceSpans[].scopeSpans[].spans[] | select(.name=="progress.git.op" and .status.statusCode=="ERROR")' data/observability/traces.jsonl

# Latest metrics frame, business events only
tail -n 1 data/observability/metrics.jsonl | jq '.resourceMetrics[].scopeMetrics[].metrics[] | select(.name | startswith("progress."))'
```

For slow operations, subtract `startTimeUnixNano` from `endTimeUnixNano` (nanoseconds). The `progress.git.op.duration` / `progress.ai.call.duration` histograms in `metrics.jsonl` give latency distributions directly.

## Log correlation

`opentelemetry-instrumentation-logging` injects `trace_id` / `span_id` into every structlog record, so each line in `data/logs/progress.log` carries the trace it belongs to:

```
{"event": "repo miniflux/v2: processing (branch=main)", "level": "info", "trace_id": "d43854b45b94ab91fee0463fe92a72c7", "span_id": "96c94a0e779ed563"}
```

Grab the `trace_id` from a log line and reconstruct the full trace from `traces.jsonl` with the jq snippet above.

## Bugsink setup

1. Create a project in your Bugsink instance and copy its DSN (`http://<key>@<host>:<port>/<project-id>`).
2. Set `core.observability.bugsink.dsn` via the Web UI, or `PROGRESS_OBSERVABILITY__BUGSINK__DSN` in the container environment.
3. Errors and unhandled exceptions now flow to Bugsink, tagged with `environment`, `release` (`progress@<version>`), and `component` (`cli` / `api`). Known secret fields (`gh_token`, `authorization`, `dsn`, …) are redacted by a `before_send` hook before events leave the process.

Note: Bugsink only ingests Sentry `event` items. Performance transactions, sessions, and client reports are disabled (`traces_sample_rate=0`, `auto_session_tracking=False`, `send_default_pii=False`) — traces and metrics stay local in the JSON-Lines files.

## Notes and follow-ups

- **Retention:** in file mode the telemetry JSONL grows without bound (the file exporter appends, no built-in rotation per spec 04). Manage with an external `logrotate` (see `docs/observability-deploy.md` for a `copytruncate` recipe targeting `<state_home>/observability/*.jsonl`). In OTLP mode retention belongs to the remote stores; only the rotated `progress.log` accumulates locally.
- **Remote querying** (dashboards, Explore, alert routing) lives in `docs/monitoring.md`; deployment wiring for the collector/token in `docs/observability-deploy.md`.
