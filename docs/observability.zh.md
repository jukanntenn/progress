# 可观测性

[English](observability.md) | 中文

Progress 内置三条互补的可观测性通道：

- **OpenTelemetry** 负责**追踪**（traces）、**指标**（metrics）与**日志**（logs）。默认模式把追踪/指标以 JSON-Lines 文件写入 `<state_home>/observability/`（`traces.jsonl` / `metrics.jsonl`），日志则进入轮转的 `<state_home>/logs/progress.log`。设置 `OTEL_EXPORTER_OTLP_ENDPOINT` 可改为把三个信号全部送往 OTLP collector（见 `docs/observability-deploy.md`）；该模式下日志双写：INFO 及以上同时发往远端，文件保留为崩溃通道（crash channel）。
- **Bugsink**（自托管、与 Sentry 兼容的服务器）只接收**错误与崩溃**，数据经 `sentry-sdk` 发送。它不摄入追踪/指标/会话。
- **可用性监控**（Uptime Kuma 探针 + 运行结果推送心跳）是独立的一层，记录在 `docs/monitoring.md`。

OTel 信号**始终开启**（采样率 = 1.0，代码常量）：没有 `[observability.otel]` 配置 section，也没有 `enabled` 开关。Bugsink 需显式启用：通过存于数据库的 `[core.observability.bugsink]` section 或 `PROGRESS_OBSERVABILITY__BUGSINK__*` 环境变量配置，DSN 为空即禁用。

## 环境标识

`deployment.environment.name` 每次启动解析一次：标准环境变量 `OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=<env>`（以及 `OTEL_SERVICE_NAME`）优先于配置默认值（`core.observability.bugsink.environment`，`"production"`）。解析结果同时供给 OTel resource 与 Bugsink 的 `environment` 标签，因此 Grafana 与 Bugsink 绝不会给同一次部署标上不同环境。容器部署只通过环境变量注入标识，不改配置 schema。

## OTLP 模式（远程遥测）

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://<otel-collector>:4318
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<token>
OTEL_EXPORTER_OTLP_COMPRESSION=gzip
OTEL_SERVICE_NAME=progress
OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name=staging
```

（上述变量由 OTel SDK 原生读取；Ansible compose 模板仅在 endpoint 与 token 都已定义时才注入该配置块，任一缺失即文件模式，也就是部署层面的降级路径。）

endpoint 设置后：

- **追踪/指标**经 OTLP HTTP 导出（指标每 60 秒一次，span 批量发送）。本地不再写 JSONL。
- **日志**由 `OtelLogHandler` 桥接：一个标准库 handler，把每条记录恰好转发一次——level 映射 severity，事件名作 body，其余标量字段作属性，并原生附带实时追踪上下文（VictoriaLogs 把 `trace_id` 暴露为 Jaeger 链接字段）。DEBUG 只进文件；无论 collector 是否中断，轮转文件保留全部内容。
- **运行时指标**来自 `opentelemetry-instrumentation-system-metrics`（进程内存/CPU/线程、系统 gauge），提供常在的锚点序列（anchor series），「遥测断流」告警盯住它，用于捕捉应用→collector→存储链路的断裂。
- **调度器 gauge** 导出运行节奏：`progress.schedule.expected_max_gap_seconds`（布防（arm）时由 cron 算出）与 `progress.pipeline.last_success_epoch`。告警窗口以导出的间隔为除数，因此修改 `schedule.cron` 会自动重调告警，不预设运行次数。
- `PROGRESS_KUMA_PUSH_URL`（可选）让进程内调度器把每次运行的判定结果推送到一个 Uptime Kuma push monitor，每次推送的保留期由预期间隔推导。留空即不推送；推送失败只记日志并吞掉（kuma 的静默检测是兜底）。

## 文件模式（默认/回退）

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

## 遥测来源

`setup_observability()` 在每个进程中调用一次：由 CLI（命令行界面）的 `run` 命令（`component="cli"`）和 FastAPI 应用（`component="api"`）分别调用。

- **自动插桩**：FastAPI 请求（仅 API）、SQLite（覆盖 tortoise）、出站 `aiohttp` HTTP 调用（覆盖 gidgethub）、标准库 `logging`（trace id 注入日志记录）。
- **手动 span**：`progress.run` / `progress.check`（运行根）、`progress.integration.<name>`（每个集成）、`progress.git.op`（每个 git 子进程）、`progress.ai.call`（AI（人工智能）提取）、`progress.changelog.parse`。
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

- **保留**：文件模式下遥测 JSONL 会无限增长（文件 exporter 只追加，无内置轮转）。用外部 `logrotate` 管理（针对 `<state_home>/observability/*.jsonl` 的 `copytruncate` 配方见 `docs/observability-deploy.md`）。OTLP 模式下保留归远端存储负责，本地只累积轮转的 `progress.log`。
- **远程查询**（仪表盘、Explore、告警路由）见 `docs/monitoring.md`；collector/token 的部署接线见 `docs/observability-deploy.md`。
