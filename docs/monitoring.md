# Monitoring runbook (Grafana · Uptime Kuma · degradation)

English | [中文](monitoring.zh.md)

This is the operational companion to [`observability.md`](./observability.md): where telemetry is queried, which layer owns which alert, and how to verify the fallback works. One fault, one owner — no signal is watched in two places at the same layer.

## The stack and where to look

| Signal | Store | Grafana datasource | Query entry |
|---|---|---|---|
| metrics | VictoriaMetrics (`victoriametrics:8428`, NAS) | `victoria-metrics` (PromQL/MetricsQL) | dashboards + Explore |
| logs | VictoriaLogs (`victorialogs:9428`, NAS) | `victoria-logs` (LogsQL) | dashboards (embedded log panels) + Explore |
| traces | Jaeger v2 (`jaeger:16686`, NAS) | `jaeger` | log line → "View trace in Jaeger" link, or Explore |

All three are fronted by one `otelcol-contrib` on the NAS (`192.168.5.57:4318`, bearer-token admission, fail-closed). Grafana lives at `http://192.168.5.57:3000/` (LAN) / `https://grafana.bytehome.fun/` (WAN). Daily use: **Dashboards → progress folder → pick a board → time range (top right) + env dropdown (top left)**. Explore is for ad-hoc investigation only. Scripts and agents can query the stores' HTTP APIs directly (VictoriaMetrics `/api/v1/query`, VictoriaLogs `/select/logsql/query`, Jaeger `/api/traces`).

Environment separation is a single dashboard set with an `env` variable over the standard `deployment.environment.name` attribute — never a copy per environment. The VictoriaLogs datasource carries a derived-field link (`trace_id` → Jaeger), so logs and traces cross-navigate everywhere, dashboards included.

## Dashboards (folder `progress`, file-provisioned on the NAS)

| Dashboard | Answers |
|---|---|
| progress Overview | Is the service healthy and delivering? Run outcomes, report/notification counts, compact HTTP RED, hours-since-last-success vs expected gap, WARN+ log stream |
| progress HTTP | Is the UI/API serving well? Per-route QPS / p95 / status codes / 5xx — SQLite contention during runs shows up here |
| progress Pipeline & Integrations | Did the core workload do its job? Integration outcomes and durations, AI/git dependency health, data-quality degradation counters (early warnings of silent failure) |
| progress Runtime & Telemetry | Is the process and the telemetry pipeline itself OK? Memory/CPU/threads, anchor-series freshness, ERROR log pressure and stream |

The provisioning files live on the NAS at `~/docker/grafana/provisioning/` (`dashboards/json/progress/*.json`, `progress.yml`, `alerting/rules-progress.yaml`, and the shared `contact-points.yaml` / `policies.yaml`). They are infrastructure-side handoff material, deliberately not in this repository; this runbook and the RFC are the in-repo record of what they contain.

## Alert ownership

| Layer | Owner | Signals |
|---|---|---|
| Edge/origin availability | **Uptime Kuma** (`192.168.5.50:3001`) | web UI probe, `/readyz` probe (DB-aware), pipeline heartbeat (push) |
| Host resources | **Beszel** (pre-existing, out of scope here) | disk/memory/CPU/agent-down |
| App, business, pipeline, telemetry pipeline | **Grafana-managed alerting** (folder `progress`, group `progress-app`, 1m) | rules below |

Rule inventory (`rules-progress.yaml`, labels carry `service: progress`; notification policy routes on that label to the `progress-alerts` contact point → email → mailrise → Feishu, grouped by `alertname` + `deployment.environment.name`):

| Rule | Severity | Fires when |
|---|---|---|
| pipeline run failed | warning | any run failure within 30m (5m debounce) |
| pipeline failing repeatedly | critical | ≥2 failures within 6h |
| pipeline silent | critical | no success within 1.5× the app-declared expected max gap + 30m grace — cadence-agnostic by design |
| integration failures occurring | warning | any integration failure within 30m (per-integration instances) |
| AI call failures occurring | warning | any AI call failure within 30m (per-model instances) |
| git op failures occurring | warning | any git op failure within 30m (per-command instances) |
| notification failures occurring | warning | a report notification failed within 1h |
| HTTP 5xx occurring | warning | >2 5xx responses within 10m |
| telemetry gap (staging) | critical | anchor series `process.memory.usage` unseen for 10m — the app→collector→store path is broken |
| data-quality degradation | warning | >5 fallback/parse/diff/unmatched events within 1h — reports degraded but still produced |
| ERROR log rate high | warning | >15 ERROR lines/min over 5m — provisioned **paused**: the victoriametrics-logs datasource emits integer frames (known wart, same as markpost's identical rule) |

The production-environment telemetry-gap rule is added on promotion day (adding it while production runs the old build would fire permanently).

## Uptime Kuma monitors

Group `progress · staging` (production group added on promotion day), leaves with tags `env:` / `service:progress` / `layer:`:

| Monitor | Type | Meaning |
|---|---|---|
| `progress · stg · web ui (origin)` | HTTP GET `/` | Caddy + SPA + proxy chain reachable from outside |
| `progress · stg · readiness (origin)` | HTTP GET `/readyz` | same + database answers (`SELECT 1`) — both red = process/host, only this red = DB |
| `progress · stg · pipeline heartbeat (push)` | push | the serve process pushes each run's verdict (`status=up/down`, msg, dynamic `ping` retention = 2× expected gap + 30m, capped 24h); best-effort — kuma's silence detection is the backstop |

The push URL is a vault secret (`kuma_push_url`, bare URL — the app appends its own query string). `PROGRESS_KUMA_PUSH_URL` empty disables the push entirely.

Known structural risk, recorded as-is: kuma is single-instance on the oect host; if that host dies, availability monitoring is blind — the Grafana telemetry-gap rules and Beszel are the cross-check. Moving/doubling kuma is infrastructure evolution, not a progress concern.

## Degradation drills (run after wiring changes)

1. **Collector outage** — on the NAS: `docker stop otelcol`. Expect: progress containers unaffected (no restart, no hang); `progress.log` keeps growing locally with SDK export failures at WARNING; `docker start otelcol` → telemetry resumes within minutes without restarting progress; the telemetry-gap alert fired and recovered.
2. **Mode fallback** — redeploy with `progress_otlp_token` unset: the compose guard drops the OTLP block and the app writes `data/observability/*.jsonl` again (file mode is the default, not a code path change).
3. **Heartbeat off** — deploy with an empty `kuma_push_url`: the scheduler logs once and skips pushes; no errors.
4. **Threshold tuning** — initial thresholds (5xx >2, data-quality >5/h, ERROR >15/min) are first guesses; adjust in `rules-progress.yaml` on the NAS and record the change here.

## Triage path

Symptom → panel → logs → trace: open the relevant dashboard, read the stat row (what), scan the embedded log panel (which component, the `event` field), click "View trace in Jaeger" on a suspicious line (why, per-span timing). Availability symptoms start in kuma instead. Errors with full stack traces are in Bugsink (`http://192.168.5.50:8770/`) regardless of the above — it is an independent fourth channel.
