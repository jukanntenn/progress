# Observability Integration: OpenTelemetry + Bugsink

A full design, implementation, and verification record of the work that added
observability to Progress: OpenTelemetry **traces and metrics** exported as
JSON-Lines to the local filesystem (no external collector), and **errors /
crashes** sent to a self-hosted **Bugsink** (Sentry-compatible) server via
`sentry-sdk`.

**Status:** complete. Implementation done, acceptance passed (48/48 checks),
backend suite **473 passing**, `ruff` clean. Changes are uncommitted at the time
of writing. User-facing guide: [`../guides/observability.md`](../guides/observability.md).

---

## 1. Background & Goals

Add observability so that **humans or an AI** can inspect telemetry to understand
bottlenecks, bugs, performance, and whether the pipeline ran as expected.

- **OpenTelemetry** → local files only ("暂无外部服务"). Output is for direct
  reading / searching.
- **Bugsink** runs at `http://192.168.5.50:8770/` as the curated error/crash
  dashboard.

The two are **complementary and never share a sink**: OTel owns traces/metrics,
Bugsink owns errors. Source/docs for both were studied in
`~/Workspace/contexts/{bugsink,open-telemetry}` (reference only — not vendored).

---

## 2. Research Findings

### 2.1 Bugsink (Sentry protocol v7)

- **Client SDK:** standard `sentry-sdk` (2.x); Bugsink is Sentry-SDK compatible.
- **DSN format:** `http://{public_key}@{host}:{port}/{project_id}`
  (project_id is an integer DB pk; public_key is a per-project UUID).
- **Ingest endpoint:** `POST /api/{project_id}/envelope/` (envelope format);
  legacy `POST /api/{project_id}/store/`. Auth via `X-Sentry-Auth` / DSN key.
- **Critical limitation:** Bugsink's ingest path processes **only** `event` and
  `attachment` envelope items. It **explicitly skips** `transaction` (traces),
  `session`/`sessions`, `client_report`, `replay_*`, `profile_*`, `check_in`,
  `log`, `otel_log`. → Traces, metrics, sessions, and OTel logs cannot go to
  Bugsink. This forces the roles split (errors-only to Bugsink).
- **Quotas / limits:** per-project default retention 10,000 events; rate limits
  return HTTP 429; `MAX_EVENT_SIZE` 1 MiB.
- **Implication for client init:** `traces_sample_rate=0`,
  `auto_session_tracking=False`, `send_client_reports=False` (avoid sending items
  Bugsink discards).

### 2.2 OpenTelemetry Python (v1.43.0 / instrumentation 0.64b0)

- **Signals:** traces ✅ stable, metrics ✅ stable, logs ⚠️ *Development*
  maturity (API may change) → OTel-native log export deferred.
- **File output:** a dedicated `opentelemetry-exporter-otlp-json-file`
  (`FileSpan/Metric/LogExporter`) exists **but is not installable from PyPI** —
  its transitive dependency `opentelemetry-proto-json` is unpublished (see
  §5). The SDK's built-in **Console exporters** (`ConsoleSpanExporter`,
  `ConsoleMetricExporter`) accept an `out=<file>` stream and a custom
  `formatter`, and emit `to_json()` per record.
- **Auto-instrumentation available:** FastAPI, sqlite3 (covers peewee via dbapi),
  requests, httpx, logging (trace-context injection), click, asyncio.
- **`opentelemetry-instrument` CLI** can wrap a process zero-code, but file
  paths + shared setup across two entry points favor programmatic setup.
- **Context across threads:** OTel context is `contextvars`-based and does **not**
  auto-propagate into `ThreadPoolExecutor` workers; it must be captured and
  re-attached per worker for the per-repo span tree to nest under `progress.check`.

### 2.3 Progress codebase (integration points)

- **Two entry points:** the CLI `progress check` (run per cron tick via
  supercronic — a **short-lived** process) and the **long-lived** FastAPI server
  (`progress.main:app`). Both share `initialize_components()` / `create_app()`.
- **Config architecture (post file→DB refactor):** TOML file = **seed + infra**
  (`data_dir`, `workspace_dir`, db path, schedule); DB blob = editable app config
  driving the web UI. Infra fields live in `INFRA_FIELDS` + `EXCLUDED_FROM_BLOB`
  in `config_store.py`.
- **Existing logging:** stdlib `logging` via `log.py` → `data/progress.log`
  (`RotatingFileHandler`) + console.
- **External I/O worth tracing:** AI analysis = `subprocess.run("claude"/"codex")`
  in `ai/runner.py` (single chokepoint `run_tool`); git/gh ops in `github.py`;
  per-repo work in `contrib/repo/repository.py` `RepositoryManager.check` /
  `check_all` (uses a `ThreadPoolExecutor`).

---

## 3. Design Decisions

Confirmed via the `grill-me-sleek` interview (22 decisions; user accepted the
recommended answer on 21, and on one — retention — chose to defer). Summary:

| # | Decision | Choice |
|---|---|---|
| 1 | Roles split | OTel → traces/metrics to files; `sentry-sdk` → errors only to Bugsink |
| 2 | Entry points | Instrument **both** CLI cron pipeline and FastAPI server |
| 3 | Frontend scope | Backend (Python) only for now |
| 4 | File exporter | Dedicated file exporter *(adapted — see §5)* |
| 5 | File layout | `data/telemetry/{traces,metrics}.jsonl`, one file per signal |
| 6 | Retention | **Deferred** — accept growth for now (low-volume internal tool) |
| 7 | Signals | Traces + metrics now; OTel-native logs deferred |
| 8 | Logs | Inject trace ids into existing `progress.log` (not OTel logs) |
| 9 | Sampling | 100% (`ALWAYS_ON`, parent-based) |
| 10 | Setup style | Programmatic `telemetry.py` (`setup_observability(cfg)`), mirrors `log.py` |
| 11 | Instrumentors | Auto: FastAPI, sqlite3, requests, logging. Manual: AI subprocess, git, per-repo tree |
| 12 | Span tree | `progress.check` → `repo.sync` / `repo.analyze` / `ai.call` |
| 13 | CLI flush | CLI: `SimpleSpanProcessor` + `force_flush`/`shutdown`; server: `BatchSpanProcessor` + shutdown event |
| 14 | Bugsink scope | `traces_sample_rate=0`, sessions/client-reports off, errors + FastAPI integration |
| 15 | `before_send` | Scrub known secret keys; keep stack traces |
| 16 | Bugsink tags | `environment`, `release`, `component` (+ repo/kind when available) |
| 17 | Config placement | New `[observability]` **infrastructure** section (TOML + env), like `data_dir`; not in the blob |
| 18 | Business metrics | `repos.checked`, `analysis.duration`, `analysis.failures`, `notifications.sent`, `reports.generated` |
| 19 | Docker | Telemetry under `data_dir` volume; DSN via env; no s6 script changes |
| 20 | Consumption | Raw JSON-Lines + `guides/observability.md` (jq recipes); no query CLI yet |
| 21 | Tests | Telemetry defaults off → hermetic pytest; no-op-when-disabled test |
| 22 | Packaging | `uv add` from PyPI; context repos are reference only |

---

## 4. Implementation

### 4.1 Architecture

A single module `src/progress/telemetry.py` exposes `setup_observability(cfg,
*, component)`, `shutdown_observability()`, `instrument_fastapi_app(app)`,
`get_tracer()`, and business-metric recorders. It is called once per process:
from `_run_check_command` in `cli.py` (`component="cli"`) and from `create_app`
in `api/__init__.py` (`component="api"`). Telemetry is **opt-in infrastructure**
— disabled by default; providers are only configured when `[observability]` is
present, so all OTel APIs are no-ops (and no files/network) otherwise.

### 4.2 Configuration model (`src/progress/config.py`)

New models added before the `Config` class:

- `OTelConfig`: `enabled`, `export_dir` (default `data/telemetry`), `traces`,
  `metrics`, `sampling_rate` (0–1, default 1.0).
- `BugsinkConfig`: `dsn` (secret — `writeOnly`/`format: password`), `environment`.
- `ObservabilityConfig`: `otel` + `bugsink`.

`Config` gains `observability: ObservabilityConfig`. In `config_store.py`,
`observability` is added to **both** `INFRA_FIELDS` and `EXCLUDED_FROM_BLOB`, so
it is resolved from the TOML/env every run and never stored in / edited through
the blob (identical treatment to `data_dir`). Both `build_runtime_config` call
sites (CLI `_resolve_runtime_config`, API `create_app`) pass `observability`
through the infra dict. Env override: `PROGRESS_OBSERVABILITY__OTEL__*` /
`PROGRESS_OBSERVABILITY__BUGSINK__*`.

### 4.3 `src/progress/telemetry.py`

- `_ThreadSafeLineFile` — append-only, UTF-8, lock-per-write + flush, so each
  JSON line is atomic and durable (short-lived CLI never loses telemetry).
- `_compact_json` — re-serializes the SDK's pretty `to_json()` as one compact
  JSON-Lines record (the Console exporters' default formatter is multi-line).
- `_setup_otel` — builds the `Resource` (`service.name=progress`, `service.version`,
  `deployment.environment`), the sampler (`ALWAYS_ON` at rate ≥ 1 else
  `ParentBased(TraceIdRatioBased)`), and wires file exporters:
  - traces → `ConsoleSpanExporter(out=traces_file, formatter=_compact_json∘to_json)`
    on `SimpleSpanProcessor` (CLI) or `BatchSpanProcessor` (server);
  - metrics → `PeriodicExportingMetricReader(ConsoleMetricExporter(...))` (5 s
    interval for CLI, 60 s for server); instruments are flushed at shutdown.
  - Then enables `LoggingInstrumentor` (trace-context injection),
    `SQLite3Instrumentor`, `RequestsInstrumentor`.
- `_register_business_metrics` — creates the 5 instruments on the real meter.
- `_setup_bugsink` — `sentry_sdk.init(dsn, environment, release=progress@<ver>,
  traces_sample_rate=0, auto_session_tracking=False, send_client_reports=False,
  send_default_pii=False, before_send=_before_send)` + `set_tag("component", …)`.
- `_before_send` / `_scrub_secret_values` — recursively redact known secret keys.
- `shutdown_observability` — flush + shutdown all providers, `sentry_sdk.flush`,
  close files, **and clear provider references** (see §6.4).
- Recorders (`record_repo_checked`, `record_analysis`, `record_notification_sent`,
  `record_report_generated`) are no-ops when disabled.

### 4.4 Wiring

- **CLI** (`cli.py` `_run_check_command`): `setup_observability(cfg.observability,
  component="cli")` right after config load; a root `progress.check` span is
  started via `context.attach`/`detach` (chosen over a `with` block to avoid
  re-indenting the 135-line work body); exceptions are recorded on the span with
  `ERROR` status; `finally` detaches, ends the span, calls
  `shutdown_observability()`, then `close_db()`.
- **API** (`api/__init__.py` `create_app`): `setup_observability(...,
  component="api")` + `instrument_fastapi_app(app)` after routes are registered;
  `shutdown_observability()` on the FastAPI shutdown event.

### 4.5 Manual spans & business metrics

- **`ai/runner.py` `run_tool`** (the claude/codex chokepoint): wraps the retry
  loop in an `ai.call` span (`ai.provider`, `ai.executable`); records
  `progress.analysis.duration` (histogram) and `progress.analysis.failures`
  (counter) in a `finally`.
- **`contrib/repo/repository.py`**: `repo.sync` span around `clone_or_update()`,
  `repo.analyze` span around `analyze_diff()` (both carry `repo.name` /
  `repo.branch`). `check_all` captures `parent_context = otel_context.get_current()`
  and re-attaches it inside each worker so child spans nest under `progress.check`
  across the `ThreadPoolExecutor`; `process()` records `progress.repos.checked`
  (`status` = success/skipped/failed).
- **`cli.py`**: `progress.notifications.sent` (per successful channel send in
  `send_notification`); `progress.reports.generated` (per saved report in
  `process_reports`).

### 4.6 Logging correlation (`src/progress/log.py`)

The `default` formatter now includes `[trace_id=%(otelTraceID)s
span_id=%(otelSpanID)s]`. An `_OtelContextFilter` (attached to both handlers)
supplies empty defaults for the four OTel log-record fields when the logging
instrumentor is not active, so the format never raises `KeyError` (e.g. in tests
or when telemetry is off). When OTel is on, real trace ids appear.

### 4.7 Packaging & deployment

Added via `uv add`: `opentelemetry-api`, `opentelemetry-sdk`,
`opentelemetry-instrumentation-{fastapi,sqlite3,requests,logging}`,
`sentry-sdk[fastapi]`. `uv.lock` and the generated `requirements.txt` updated.
Docker needs **no s6 run-script changes** (the existing `progress`/`fastapi`
commands run unchanged; the Dockerfile regenerates `requirements.txt` from
`uv.lock`). Telemetry writes under the existing `data_dir` volume; the Bugsink
DSN is supplied via env.

---

## 5. Key Deviation: file exporter → Console exporter

Decision 4 specified the new `opentelemetry-exporter-otlp-json-file`. During
implementation `uv add` failed: the exporter (0.64b0) depends on
`opentelemetry-exporter-otlp-json-common` → `opentelemetry-proto-json` (0.64b0),
and **`opentelemetry-proto-json` is not published on PyPI**. Path-installing from
the context repo would not be reproducible in Docker/CI.

**Adaptation (Decision 4 option B):** use the SDK's built-in Console exporters
pointed at per-signal files, with a compact-single-line formatter
(`_compact_json`) and a thread-safe append wrapper (`_ThreadSafeLineFile`). The
result is the same artifact — one greppable JSON object per line per span/metric
(`ReadableSpan.to_json()` / `MetricsData.to_json()`). If the file exporter lands
on PyPI later, swapping the exporter construction in `_setup_otel` is a small
change. Recorded in project memory.

---

## 6. Acceptance & Verification

### 6.1 Method

A 48-check end-to-end acceptance script exercising every path through the real
code (setup, manual spans, business metrics, `sentry-sdk` → Bugsink, log
correlation, FastAPI/sqlite3/requests auto-instrumentation, disabled no-op);
independent raw-envelope `curl` of the Bugsink ingest endpoint; a
`sentry-sdk.debug` diagnostic of the actual HTTP outcome; plus the full pytest
suite and `ruff`.

### 6.2 Results matrix

| Area | Checks | Result |
|---|---|---|
| Config plumbing (load, secret flag, blob exclusion, env override) | 7 | ✅ |
| OTel Traces (file, JSON-Lines, span tree, attributes, resource) | 17 | ✅ |
| OTel Metrics (file, 5 instruments, data-point attributes) | 9 | ✅ |
| Bugsink (init, DSN, options, `before_send`, tags, delivery) | 8 | ✅ |
| Log correlation (trace id in `progress.log`) | 1 | ✅ |
| Auto-instrumentation (FastAPI / sqlite3 / requests) | 3 | ✅ |
| Disabled / idempotency | 3 | ✅ |
| **Acceptance total** | **48** | **48 / 48 PASS** |

Backend suite **473 passing** (incl. new `tests/test_telemetry.py`, 6 tests);
`ruff check` clean.

### 6.3 Bugsink ingest verification (DSN `…@192.168.5.50:8770/2`)

- **Raw envelope `POST /api/2/envelope/`** → **HTTP 200**, body
  `{"id":"58210c809fdf426d8b28f5d262e2cb0d"}` — confirms DSN, project_id=2, and
  the public key authenticate and the server accepts Sentry-format envelopes.
- **`sentry-sdk` via our `setup_observability`** → debug log
  `POST /api/2/envelope/ HTTP/1.1" 200`; `capture_exception` returns a valid
  32-hex event_id. Confirms our code path delivers to Bugsink.

### 6.4 Issues found during acceptance (and fixed)

1. **`shutdown_observability()` did not clear provider references** (real defect).
   After an enabled run + shutdown, a subsequent **disabled** setup reported
   `is_enabled() == True`, because `setup_observability`'s enabling condition
   (`if _STATE.tracer_provider or _STATE.meter_provider or cfg.bugsink.dsn`) saw
   the stale provider refs. The existing unit test missed it due to test ordering
   (disabled test ran before the enabled one). **Fix:** `shutdown_observability`
   now clears `tracer_provider` / `meter_provider` / `metric_reader`.
   **Regression test:** `test_shutdown_clears_provider_references` (probes state
   directly to avoid OTel's global provider "set-once" constraint).
2. **Acceptance-script misread of `sentry_sdk.flush()`** (not a code defect).
   The script asserted `flush() is True`; `flush()` returns `None` in `sentry-sdk`
   2.x. Debug output confirmed the event was delivered (HTTP 200). Corrected the
   assertion.

---

## 7. Known Follow-ups

- **Retention (deferred, Decision 6):** telemetry files grow unbounded under
  100% sampling. Add a periodic prune (the existing supercronic slot) or per-run
  files before long-term production use.
- **OTel-native logs (deferred, Decision 7):** export stdlib logs as OTel
  LogRecords once the logs signal stabilizes; trace-id injection into
  `progress.log` covers correlation today.
- **Optional `repo.check` parent span:** the per-repo grouping currently relies on
  `repo.name` attributes + context propagation rather than an explicit
  `repo.check` wrapper span (avoided a fragile 120-line re-indent). A focused
  follow-up if stricter per-repo trace grouping is wanted.
- **File exporter on PyPI:** if `opentelemetry-proto-json` is published, swap the
  Console exporters for `FileSpanExporter` / `FileMetricExporter` (§5).
- **Frontend observability** (Decision 3): backend-only for now; Next.js error
  capture (`@sentry/react`) is a later phase.

---

## 8. File Inventory

**New**
- `src/progress/telemetry.py` — OTel + Bugsink setup, exporters, metrics, scrub.
- `tests/test_telemetry.py` — 6 tests (incl. shutdown-ref regression).
- `guides/observability.md` — user guide (config, JSON-Lines schema, jq recipes).
- `docs/observability.md` — this design/implementation/verification record.

**Modified**
- `src/progress/config.py` — `OTelConfig` / `BugsinkConfig` / `ObservabilityConfig`.
- `src/progress/config_store.py` — `observability` in `INFRA_FIELDS` + `EXCLUDED_FROM_BLOB`.
- `src/progress/cli.py` — setup + `progress.check` root span + flush + metrics.
- `src/progress/api/__init__.py` — setup + `instrument_fastapi_app` + shutdown.
- `src/progress/ai/runner.py` — `ai.call` span + analysis metrics.
- `src/progress/contrib/repo/repository.py` — `repo.sync`/`repo.analyze` spans,
  context propagation, `repos.checked` metric.
- `src/progress/log.py` — trace-id fields + `_OtelContextFilter`.
- `config.example.toml` — `[observability.otel]` / `[observability.bugsink]`.
- `pyproject.toml`, `uv.lock`, `requirements.txt` — new dependencies.
- `CLAUDE.md` — project-structure pointers.

---

## 9. How to Enable

```toml
[observability.otel]
enabled = true                 # traces + metrics → data/telemetry/*.jsonl
[observability.bugsink]
dsn = "http://<key>@192.168.5.50:8770/<project-id>"
environment = "production"
```

…or the equivalent `PROGRESS_OBSERVABILITY__*` environment variables (the Docker
path). OTel and Bugsink are independent — enable either or both. See
[`../guides/observability.md`](../guides/observability.md) for the JSON-Lines
schema and example `jq` queries.
