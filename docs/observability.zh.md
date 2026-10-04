# 可观测性

[English](observability.md) | 中文

Progress 内置两条互补的可观测性通道：

- **OpenTelemetry** 把**追踪**（traces）与**指标**（metrics）以 JSON-Lines 文件导出到 `<state_home>/observability/`（`traces.jsonl` / `metrics.jsonl`）。默认没有外部 collector，由人或 AI（人工智能）读取并检索这些文件，理解瓶颈、故障、性能，以及流水线是否按预期运行。设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 可改为发送到 OTLP collector。
- **Bugsink**（自托管、与 Sentry 兼容的服务器）只接收**错误与崩溃**，数据经 `sentry-sdk` 发送。它不摄入追踪/指标/会话。

OTel 追踪与指标**始终开启**（采样率 = 1.0，spec 04 规定的代码常量）：没有 `[observability.otel]` 配置 section，也没有 `enabled` 开关。Bugsink 需显式启用：通过存于数据库的 `[core.observability.bugsink]` section 或 `PROGRESS_OBSERVABILITY__BUGSINK__*` 环境变量配置，DSN 为空即禁用。

## 配置

Bugsink 是一个 Web 类配置字段（数据库 `config` 表，`section="core"`）：

```toml
[core.observability.bugsink]
dsn = "http://<public-key>@<host>:<port>/<project-id>"  # empty → disabled + warning
environment = "production"
```

环境变量覆盖（供 Docker / `docker-compose` 使用）：

```
PROGRESS_OBSERVABILITY__BUGSINK__DSN=http://<key>@192.168.5.50:8770/<project-id>
PROGRESS_OBSERVABILITY__BUGSINK__ENVIRONMENT=production
```

要把 OTel exporter 从本地文件切换到 OTLP HTTP collector：

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://<otel-collector>:4318
```

未设置时，追踪/指标经 `opentelemetry-exporter-otlp-json-file` 文件 exporter 写入 `<state_home>/observability/traces.jsonl` 与 `<state_home>/observability/metrics.jsonl`。

## 遥测来源

`setup_observability()` 在每个进程中调用一次：由 CLI（命令行界面）的 `run` 命令（`component="cli"`）和 FastAPI 应用（`component="api"`）分别调用。

- **自动插桩**：FastAPI 请求（仅 API）、SQLite（覆盖 tortoise）、出站 `aiohttp` HTTP 调用（覆盖 gidgethub）、标准库 `logging`（trace id 注入日志记录）。
- **手动 span**：`progress.run` / `progress.check`（运行根）、`progress.integration.<name>`（每个集成）、`progress.git.op`（每个 git 子进程）、`progress.ai.call`（AI 提取）、`progress.changelog.parse`。
- **业务事件**（`record_business_event`）：`progress.run.started`、`progress.run.completed`、`progress.integration.run`、`progress.repos.checked`、`progress.git.diff_decided`、`progress.git.diff_failed`、`progress.releases.truncated`、`progress.changelog.sync`、`progress.markpost.published` 等。

跨信号关联依赖 OTel 的 `trace_id`（没有显式 run_id）：一次 `core.run()` 里的每个 span 共享同一条追踪，`structlog` 把 `trace_id`/`span_id` 注入每条日志记录，让日志与追踪无缝衔接。

## 输出格式

### `traces.jsonl`

标准 OTLP JSON 文件格式：每次导出刷新写一个 resource-spans 对象。每个 `scopeSpans[].spans[]` 条目是一个 span，带 `name`、`traceId`、`spanId`、`parentSpanId`、`startTimeUnixNano`、`endTimeUnixNano`、`attributes`、`status`。没有 `parentSpanId` 的 span 是一条追踪的根。

### `metrics.jsonl`

标准 OTLP JSON 文件格式：`resourceMetrics[].scopeMetrics[].metrics[]`，每个指标带 `name`，以及承载数值和属性的 `sum`/`histogram` 数据点（例如 `{"status":"success"}`、`{"repo":"foo/bar"}`）。由周期性指标读取器每 60 秒导出一次，并在关闭时做最终刷新。

## 用 jq 查询

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

排查慢操作时，用 `endTimeUnixNano` 减去 `startTimeUnixNano`（纳秒）。`metrics.jsonl` 里的 `progress.git.op.duration` / `progress.ai.call.duration` 直方图直接给出延迟分布。

## 日志关联

`opentelemetry-instrumentation-logging` 把 `trace_id` / `span_id` 注入每条 structlog 记录，因此 `data/logs/progress.log` 的每一行都携带它所属的追踪：

```
{"event": "repo miniflux/v2: processing (branch=main)", "level": "info", "trace_id": "d43854b45b94ab91fee0463fe92a72c7", "span_id": "96c94a0e779ed563"}
```

从日志行取出 `trace_id`，用上面的 jq 片段从 `traces.jsonl` 重建完整追踪。

## Bugsink 设置

1. 在你的 Bugsink 实例里创建一个项目，复制它的 DSN（`http://<key>@<host>:<port>/<project-id>`）。
2. 通过 Web UI 设置 `core.observability.bugsink.dsn`，或在容器环境里设置 `PROGRESS_OBSERVABILITY__BUGSINK__DSN`。
3. 此后错误与未处理异常会流入 Bugsink，并带上 `environment`、`release`（`progress@<version>`）、`component`（`cli` / `api`）标签。已知机密字段（`gh_token`、`authorization`、`dsn`、……）在事件离开进程前由 `before_send` 钩子脱敏。

注：Bugsink 只摄入 Sentry 的 `event` 条目。性能事务、会话与客户端报告均已禁用（`traces_sample_rate=0`、`auto_session_tracking=False`、`send_default_pii=False`），追踪与指标保留在本地 JSON-Lines 文件里。

## 备注与后续事项

- **保留**：遥测文件会无限增长（文件 exporter 只追加，按 spec 04 无内置轮转）。用外部 `logrotate` 管理（针对 `<state_home>/observability/*.jsonl` 的 `copytruncate` 配方见 `docs/observability-deploy.md`）。
- **OTel 原生日志**（把标准库日志导出为 OTel LogRecord）暂缓：logs 信号仍处于 Development 成熟度；目前 `progress.log` 中的 trace id 已覆盖关联需求。
