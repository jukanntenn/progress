# Observability

Progress ships two complementary observability channels:

- **OpenTelemetry** exports **traces** and **metrics** as JSON-Lines files to the
  local filesystem. There is no external collector — humans or an AI read and
  search these files to understand bottlenecks, failures, performance, and
  whether the pipeline ran as expected.
- **Bugsink** (a self-hosted, Sentry-compatible server) receives **errors and
  crashes** only, via `sentry-sdk`. It does not ingest traces/metrics/sessions.

Both are **opt-in infrastructure**: disabled by default, configured through the
`[observability]` section of the TOML file or `PROGRESS_OBSERVABILITY__*`
environment variables (same precedence as `data_dir`), and never stored in the
editable config blob.

## Configuration

```toml
[observability.otel]
enabled = true                 # enable traces + metrics export
export_dir = "data/telemetry"  # traces.jsonl / metrics.jsonl live here
traces = true                  # set false to skip traces
metrics = true                 # set false to skip metrics
sampling_rate = 1.0            # 1.0 = capture everything (recommended here)

[observability.bugsink]
dsn = "http://<public-key>@<host>:<port>/<project-id>"  # empty disables
environment = "production"
```

Environment overrides (used by Docker / `docker-compose`):

```
PROGRESS_OBSERVABILITY__OTEL__ENABLED=true
PROGRESS_OBSERVABILITY__OTEL__EXPORT_DIR=/app/data/telemetry
PROGRESS_OBSERVABILITY__BUGSINK__DSN=http://3a2b8c9d@192.168.5.50:8770/1
PROGRESS_OBSERVABILITY__BUGSINK__ENVIRONMENT=prod
```

OTel and Bugsink are independent: enable either or both.

## Where telemetry comes from

`setup_observability()` is called once per process — from the CLI `check`
command (`component="cli"`) and from the FastAPI app (`component="api"`).

- **Auto-instrumented:** FastAPI requests, SQLite (covers peewee), outbound
  `requests` HTTP calls, and stdlib `logging` (trace ids injected into records).
- **Manual spans:** `progress.check` (the run root), `repo.sync` (git clone/pull),
  `repo.analyze` (AI analysis), `ai.call` (the `claude`/`codex` subprocess).
- **Business metrics:** `progress.repos.checked`, `progress.analysis.duration`,
  `progress.analysis.failures`, `progress.notifications.sent`,
  `progress.reports.generated`.

The short-lived CLI run uses a synchronous span processor and flushes on exit,
so nothing is lost when a cron tick finishes. The long-lived API server batches
exports and flushes on shutdown.

## Output format

### `traces.jsonl`

One compact JSON object per line, one line per span:

```json
{"name":"repo.sync","context":{"trace_id":"0x…","span_id":"0x…"},"kind":"SpanKind.INTERNAL","parent_id":"0x…","start_time":"2026-06-28T00:12:17.315414Z","end_time":"2026-06-28T00:12:17.315423Z","status":{"status_code":"UNSET"},"attributes":{"repo.name":"foo/bar"},"events":[],"resource":{"attributes":{"service.name":"progress","service.version":"0.0.1"}}}
```

A span with `"parent_id": null` is a trace root. All spans sharing a
`context.trace_id` belong to one trace.

### `metrics.jsonl`

One JSON object per periodic export (and one final export at shutdown). The
metric instruments live under
`resource_metrics[].scope_metrics[].metrics[]`, each with `name` and
`data.data_points[]` carrying the counter/histogram values and their attributes
(e.g. `{"status":"success"}`, `{"provider":"claude_code"}`).

## Querying with jq

```bash
# Every span, trimmed to the essentials
jq -c '{name, trace: .context.trace_id, span: .context.span_id, parent: .parent_id}' data/telemetry/traces.jsonl

# All spans for one repository
jq -c 'select(.attributes["repo.name"]=="foo/bar")' data/telemetry/traces.jsonl

# Reconstruct one trace by id
jq -c 'select(.context.trace_id=="0x8bef3a7e7124…")' data/telemetry/traces.jsonl

# Failed AI calls
jq -c 'select(.name=="ai.call" and .status.status_code=="ERROR")' data/telemetry/traces.jsonl

# List distinct span names emitted
jq -r .name data/telemetry/traces.jsonl | sort -u
```

For slow operations, compare `start_time` and `end_time` (ISO-8601). The
`progress.analysis.duration` histogram in `metrics.jsonl` gives AI-call latency
distributions directly.

## Log correlation

When OTel is enabled, `opentelemetry-instrumentation-logging` injects
`trace_id` / `span_id` into every log record, so each line in `data/progress.log`
carries the trace it belongs to:

```
2026-06-28T00:12:17 [INFO] [trace_id=0x8bef3a7e7124… span_id=0x5fce4f5f…] [MainProcess] …
```

Grab the `trace_id` from a log line and reconstruct the full trace from
`traces.jsonl` with the jq snippet above. (When telemetry is off these fields
render empty — the log format is always safe.)

## Bugsink setup

1. Create a project in your Bugsink instance and copy its DSN
   (`http://<key>@<host>:<port>/<project-id>`).
2. Set `observability.bugsink.dsn` (or `PROGRESS_OBSERVABILITY__BUGSINK__DSN`).
3. Errors and unhandled exceptions now flow to Bugsink, tagged with
   `environment`, `release` (`progress@<version>`), and `component`
   (`cli` / `api`). Known secret fields (`gh_token`, `authorization`, `dsn`, …)
   are redacted by a `before_send` hook before events leave the process.

Note: Bugsink only ingests Sentry `event` items. Performance transactions,
sessions, and client reports are disabled (`traces_sample_rate=0`,
`auto_session_tracking=False`, `send_client_reports=False`) — traces and metrics
stay local in the JSON-Lines files.

## Notes and follow-ups

- **Retention:** telemetry files grow without bound (the exporter appends). Add a
  periodic prune (e.g. via the existing supercronic schedule) or per-run files
  before relying on long-term retention.
- **OTel-native logs** (exporting stdlib logs as OTel LogRecords) are deferred —
  the logs signal is still Development-maturity. Trace ids in `progress.log`
  cover the correlation need today.
