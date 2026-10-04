# 04 · 可观测性

## 决策:单一 OTel 插桩层 + structlog 日志 + Bugsink 仅错误

可观测性三信号(traces/metrics/logs)收敛为**单一插桩层(OTel)**,结构化日志用 structlog,错误捕获 sentry-sdk→Bugsink(traces_sample_rate=0,OTel 独占 trace)。

### 第一性原理

三套系统并存且互打(当前 OTel Console hack + sentry-sdk 并行 + stdlib logging)是病根。收敛原则(社区 2025-2026 最佳实践):
1. **OTel 是唯一插桩层**(traces + metrics)。Sentry 自己都在弃并行插桩(`OpenTelemetryIntegration` deprecated → `OTLPIntegration`,2.62.0)。
2. **structlog 注入 trace 上下文**,日志能关联 trace。
3. **Bugsink 只管错误事件**,错误携带 trace_id 关联 trace。
4. **后端分工**:traces/metrics → OTel exporter(本地文件默认 / OTLP 可配);错误 → Bugsink。Bugsink 不能收 traces(源码核实:`bugsink/ingest/urls.py` 只有 Sentry `/store/`+`/envelope/`,零 OTLP 端点)。

## OTel 配置

### Provider + Resource + Sampler

```python
# observability/telemetry.py
resource = Resource.create(
    {
        "service.name": "progress",
        "service.version": PROGRESS_VERSION,
        "deployment.environment.name": environment,  # 注:用 .name(stable semconv),非 deprecated 的 deployment.environment
    }
)
sampler = ParentBased(TraceIdRatioBased(sampling_rate))  # sampling_rate 默认 1.0(代码常量)
```

### Exporter(可配,默认本地文件)

```toml
# Ansible 类(config.toml)—— 注:开关/采样已改代码常量,exporter 模式可配
[observability.otel]
exporter = "file"          # "file"(默认,本地 JSONL) | "otlp"(远端)
otlp_endpoint = ""          # exporter="otlp" 时配置 OTLP HTTP 端点
```

- **`exporter="file"`(默认)**:用 `opentelemetry-exporter-otlp-json-file`(Beta,`FileSpanExporter`/`FileMetricExporter`),写本地 JSONL 到 `<state_home>/observability/`。
- **`exporter="otlp"`**:用 `OTLPSpanExporter`/`OTLPMetricExporter`(`opentelemetry-exporter-otlp-proto-http`),ship 到 collector 或 OTel 后端。
- **删除**当前 Console exporter + `_ThreadSafeLineFile` hack。

### Auto-instrumentation(启动时各 instrument() 一次)

```python
FastAPIInstrumentor.instrument_app(app)  # 仅 API 入口
AioHttpClientInstrumentor().instrument()  # 覆盖 gidgethub + 所有 aiohttp 调用
SQLite3Instrumentor().instrument()
LoggingInstrumentor(inject_trace_context=True).instrument()
```

**关键时序约束(源码核实)**:`AioHttpClientInstrumentor().instrument()` 包装 `ClientSession.__init__` 注入 TraceConfig(`__init__.py:681-683`)。**必须在创建 `aiohttp.ClientSession` 之前调用 `.instrument()`**,否则该 session 无 TraceConfig,调用不被追踪。

## structlog 日志

### 配置

```python
# observability/logging.py
# structlog 经 ProcessorFormatter 桥接 stdlib TimedRotatingFileHandler
handler = TimedRotatingFileHandler(
    filename=f"{state_home}/logs/progress.log",
    when="midnight",  # 日切
    backupCount=N,  # 保留 N 天
)
handler.setFormatter(ProcessorFormatter(...))
```

### 接口设计要点(源码核实)

- **ProcessorFormatter 是 `logging.Formatter` 子类**,由 **handler 持有**(`handler.setFormatter(ProcessorFormatter(...))`),不是反向包裹 handler。`structlog/src/structlog/stdlib.py:1010,1097`。
- **structlog 不自造轮转**(文档明示用 stdlib handler 或 logrotate)。
- **trace 注入 processor**:structlog 文档配方,processor 读 `trace.get_current_span()` 注入 `trace_id`/`span_id`(`docs/frameworks.md`)。

### 日志轮转(用户硬需求)

- **logs**:`TimedRotatingFileHandler(when="midnight", backupCount=N)`——日切 + 保留 N 天(stdlib 原生)。
- **traces/metrics**:OTel json-file exporter **不支持轮转**(源码核实 `_internal.py:31-36` 纯 `open(path, "a")`,无轮转)。**保持现状(append-only),不自写轮转**。接受文件持续增长,用户自行关注(④回顾确认)。

### 决策理由(日切策略)

- 用户选定 `TimedRotatingFileHandler`(日切为主,单日无大小上限)——stdlib 原生、简单。
- 否掉双层(Timed+Rotating)和外部 logrotate——增加复杂度,用户明确选简单。

## Bugsink(错误捕获)

```python
sentry_sdk.init(
    dsn=cfg.observability.bugsink.dsn,
    environment=cfg.observability.bugsink.environment,
    release=f"progress@{PROGRESS_VERSION}",
    traces_sample_rate=0,  # OTel 独占 trace
    auto_session_tracking=False,
    send_default_pii=False,
    before_send=scrub_secrets,  # 统一脱敏(见下)
)
```

- **`traces_sample_rate=0`**:禁用 Sentry 的 trace 插桩,OTel 独占(修当前 Sentry + OTel 对 FastAPI 双重插桩)。
- **错误带 trace_id**:Bugsink 展示时关联到 OTel trace。

## 密钥统一脱敏

```python
# observability/scrub.py(覆盖 Sentry + structlog + span 属性)
_SECRET_KEYS = frozenset(
    {"gh_token", "token", "password", "secret", "authorization", "webhook_url", "dsn", "api_key", ...}
)


def scrub_secrets(value) -> None:
    """递归替换已知 secret key 的值为 [REDACTED]。覆盖 Sentry event + structlog + span 属性。"""
```

- **修当前脱敏只覆盖 Sentry 的病根**:当前 `_scrub_secret_values` 只在 Sentry `before_send`;span 属性和日志记录从不脱敏(审计证实 `repo.url` 含嵌入 token 会泄漏进 traces.jsonl)。
- **统一脱敏入口**:Sentry `before_send` + structlog processor + span 属性 filter 共用 `scrub_secrets`。

## 业务指标收敛

```python
# observability/metrics.py
# 收敛 record_* API,删 record_analysis_failure 双计风险
# 用装饰器自动记录 span + metric

@observed("ai.call", attributes={"ai.provider": provider})
async def analyze(...): ...
```

- 删 `record_analysis` + `record_analysis_failure` 的双计陷阱(审计证实 `telemetry.py:362-402` 易错)。
- 用 `@observed` 装饰器自动记 span + duration histogram + failure counter。

## 插桩用 contextmanager(删手搓 attach)

```python
# 删当前 cli.py 的 start_span + otel_context.attach/detach 手工接线
# 改用标准 contextmanager
with tracer.start_as_current_span("progress.run") as span:
    ...
```

- `start_as_current_span` 自动继承父上下文,删 `repository.py` 的 `parent_context` 捕获重 attach(审计证实脆弱)。

## 各入口点的可观测性生命周期

- **CLI**:`cli/lifespan.py` 的 `@asynccontextmanager` 内 `setup_observability(component="cli")` + `finally: shutdown_observability()`。
- **API**:`api/__init__.py` 的 `_lifespan` 内 `setup_observability(component="api")`,**然后** `instrument_fastapi_app(app)`(修当前顺序 bug:当前 `instrument_app` 在 `create_app` 时调用,`_STATE.enabled=False` early-return,span 永不产生)。

## OTel Logs 信号

**启用** OTel Logs 远端信号(修订自 2026-10 前的"不用"决定;当年理由"SDK 仍在稳定中"已不成立——项目已依赖的 opentelemetry-sdk 1.44 里 logs 信号与 traces/metrics 同包同版本,零新增依赖,markpost 在同一 VictoriaLogs 上生产验证)。

- 桥接:`OtelLogHandler`(stdlib Handler)挂在 root logger 上,structlog 与 stdlib 记录各被转发**恰好一次**(Handler 语义,不受 ProcessorFormatter 多 sink 影响)。
- 级别:INFO+ 才上送;DEBUG 是文件专属(轮转有界,远端不设)。
- 结构:severity ← 级别映射,body ← event 名,attributes ← 其余标量字段;trace 上下文经 `emit(context=get_current())` 原生携带(VictoriaLogs 侧 `trace_id` 字段即 Jaeger 跳转锚点)。
- 兜底:OTLP 模式下文件日志**双写不变**(崩溃证据通道);非 OTLP 模式该 Handler 为 no-op。

## 文件结构

```
src/progress/observability/
├── __init__.py        # setup_observability / shutdown_observability + 公共 API
├── logging.py         # structlog 配置 + trace 注入 processor + 密钥脱敏
├── telemetry.py       # OTel Provider/采样/exporter(file/otlp) + auto-instrument
├── scrub.py           # 统一密钥脱敏(Sentry + structlog + span)
└── metrics.py         # 业务指标 + @observed 装饰器
```

## 默认值与开关

| 项 | 默认 | 说明 |
|---|---|---|
| logs | 始终开 | TimedRotatingFileHandler 日切(本地);OTLP 模式下 INFO+ 双写到远端 |
| traces/metrics | 默认全开 | 文件 exporter 默认;sampling 1.0 |
| exporter | `"file"` | 本地 JSONL;设 `OTEL_EXPORTER_OTLP_ENDPOINT` 环境变量走 OTLP(无 config 节) |
| sampling_rate | 1.0 | 代码常量 |
| Bugsink dsn | 空 | 空 → 错误捕获降级 + warning |
| 环境标识 | `bugsink.environment` | 标准环境变量(`OTEL_SERVICE_NAME`/`OTEL_RESOURCE_ATTRIBUTES`)优先于 config;解析结果同时喂 OTel resource 与 Bugsink |
| 运行时指标 | 开 | `opentelemetry-instrumentation-system-metrics`(process/system gauges;telemetry-gap 告警锚点) |

## 删除清单

| 删除 | 理由 |
|---|---|
| `telemetry.py` 的 `_ThreadSafeLineFile` | Console hack,改 json-file exporter |
| `record_analysis_failure`(单独函数) | 双计风险,收敛到 `@observed` |
| `log.py` 的 stdlib dictConfig | 改 structlog |
| `_OtelContextFilter` 注空 trace 字段 | structlog processor 替代 |
| `deployment.environment`(deprecated) | 改 `deployment.environment.name` |
