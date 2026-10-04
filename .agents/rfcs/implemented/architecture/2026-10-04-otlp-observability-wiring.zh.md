# RFC: OTLP 可观测性接线——三个信号、环境标识与文件回退

Status: implemented

[English](2026-10-04-otlp-observability-wiring.md) | 中文

## 问题

Progress 此前只有文件模式可观测性：追踪/指标是本地 JSONL，日志在轮转文件里，错误进 Bugsink。外部部署的可观测性栈（一个 otelcol-contrib 之后的 Jaeger / VictoriaMetrics / VictoriaLogs / Grafana）什么也收不到，于是项目没有仪表盘、没有告警、也没有可用性监控——而姊妹项目 markpost 已在同一套基础设施上把这套模式建成并经过实战检验。三个缺口挡住了照搬：deployment.environment.name 资源属性实际上硬编码为 `production`（staging 会错标自身，而 SDK 的「显式属性优先于环境变量」语义意味着标准环境变量纠正不了它）；OTel logs 信号缺席（spec 04 曾以其不成熟为由拒绝，本服务的 Grafana 日志支柱因此一直空着）；指标流没有常在序列（业务计数器只在流水线运行时才走动，一天两次），任何「遥测断流」告警都会在闲置静默时触发，而不是在链路断裂时触发。另外，每个显而易见的告警设计里都潜伏着一个节奏假设：「一天两次」是运行时配置项，不是系统的固有属性。

## 决策

**生产者侧（本仓库）。** 双模式 exporter 设计保留并扩展到全部三个信号：设置了 `OTEL_EXPORTER_OTLP_ENDPOINT` → OTLP HTTP（SDK 原生读取 `OTEL_EXPORTER_OTLP_HEADERS` / `OTEL_EXPORTER_OTLP_COMPRESSION`，因此鉴权与 gzip 都是部署环境变量，零代码）；未设置 → 文件 exporter，维持原样。日志经新的 `OtelLogHandler` 送出：root logger 上的一个标准库 handler（handler 语义保证每条记录恰好转发一次，无论后面有多少个 ProcessorFormatter sink 再格式化它），把 level 映射为 severity、事件名映射为 body、其余标量字段映射为属性，并通过 `emit(context=get_current())` 附带实时追踪上下文。INFO 及以上外发；DEBUG 只进文件；轮转的 `progress.log` 在每种模式下都双写，作为崩溃通道（crash channel）。spec 04 对 logs 信号的否决就此修订：锁定的 opentelemetry-sdk 1.44 与追踪/指标在同一批包里提供 logs（零新增依赖），且同一桥接已被 markpost 在这套栈上生产验证。

**环境标识。** `effective_environment()` 先从标准 `OTEL_RESOURCE_ATTRIBUTES` 解析 `deployment.environment.name`，其次用配置默认值；`_build_resource` 对 `OTEL_SERVICE_NAME` 采用同一优先级。解析结果由一次调用同时供给 OTel resource 与 Bugsink 的 `environment` 标签，两个后端绝不会把同一次部署标成不同环境。（天真的 `Resource.create({}).merge(...)` 写法是错的：环境变量未设置时 env detector 会捏造 `service.name="unknown_service"`，盖掉显式常量——解析器因此改为直接解析这两个环境变量。）

**常在运行时指标。** `opentelemetry-instrumentation-system-metrics`（带 psutil）在初始化时对进程插桩；`process.memory.usage` 一族即遥测断流告警盯守的锚点序列，也是 Runtime 仪表盘的面板数据。

**与节奏无关的调度可观测性。** 定时运行入口导出 `progress.schedule.expected_max_gap_seconds`（布防（arm）时按 cron 算出的下一段相邻触发之间的最大间隔）与 `progress.pipeline.last_success_epoch`（每次成功时设置）。告警窗口以导出的间隔为除数，因此修改 `schedule.cron`——一个 Web UI 运行时旋钮——无需触碰预配置规则即可重调告警。同一间隔驱动 Uptime Kuma 推送心跳：每次运行后调度器把判定结果（`status=up|down`、message、`ping` 保留期 = 2× 间隔 + 30 分钟，封顶 kuma 每次推送 24 小时的上限）推送到 `PROGRESS_KUMA_PUSH_URL`；推送是尽力而为（失败仅记日志并吞掉，kuma 的静默检测是兜底），URL 为空即禁用。

**部署接线。** Ansible compose 模板仅在 `progress_otlp_endpoint` 与 `progress_otlp_token` 都定义时注入 OTLP 块（任一缺失 → 文件模式，即部署层面的降级路径），另加 `PROGRESS_OBSERVABILITY__BUGSINK__DSN`（补上一处文档写了却没接的线）与 `PROGRESS_KUMA_PUSH_URL`。token 与推送 URL 是 vault secret；endpoint 是明文 group_vars。基础设施侧（collector token 准入、Grafana 预配置——一个含四块仪表盘、十一条告警规则的 `progress` 文件夹，`progress-alerts` contact point 与路由策略，kuma 组 + 三个 staging 叶子）是可观测性 NAS 上的交接材料，记录在 `docs/monitoring.md`。

**staging 先行上线。** 在 staging 与生产对比验证期间，生产跑的是重构前构建，不能动：collector 准入一个无人使用的生产 token，生产遥测断流规则与 kuma 组推迟到晋级日（现在就预配置会对着一个永不发射数据的构建永久触发），其余都是按环境维度展开多实例的规则，对没有序列的环境保持静默。

## 备选方案

**主机侧日志搬运（promtail/alloy 跟踪 `progress.log`）。** 落选：每台主机多两个活动部件、日志轮转竞态，还要运维第二条遥测传输通道；对手是复用已锁定 SDK 与隔壁已验证模式的双写桥接。

**配置 schema 里的 `[observability.otel]` section。** 落选：SDK 已拥有标准环境变量入口，markpost 树立了仅靠部署配置的先例，而 schema 变更要拖上 OpenAPI/前端/迁移一整串改动面，换来的能力增量为零。该 section 的 spec 04 草案在本 RFC 之前就已降为代码常量。

**每个环境复制一套仪表盘。** 败给单套加 `env` 变量的模式，理由正是 markpost 翻修自身接线时记录的：副本会静默漂移，而多维告警规则天然产出按环境的实例。

**两个环境共用一个 token。** 败给按环境分 token：影响面隔离与可独立吊销（staging 泄漏不应迫使轮换生产 token）。

**告警里硬编码节奏（「14 小时没运行」）。** 落选：`schedule.cron` 是 Web UI 运行时旋钮；应用自报预期间隔，让预配置规则在节奏变更后依然正确，正是本 RFC 交付的机制。

**现在就在共享 collector 上推进 `bearertokenauth` 重命名。** 推迟而非落选：前门与 markpost 生产共用；重命名纯属外观调整，搭晋级日的变更顺风车，而不是为了美观给热路径添折腾。

## 后果

staging 遥测以 `deployment.environment.name=staging` 出现在 Grafana（以前不可能，标签是硬编码的），日志/追踪/指标经由原生追踪上下文互相跳转，并且一条 Grafana 规则与一个 kuma 推送心跳各自独立盯守流水线——告警层继承了传输层同样的降级哲学（每条路径都假设另一条可能已倒，本地文件则假设两条都倒了）。接受的代价：有意放弃远端 DEBUG 日志（只进文件）；collector 中断期间的追踪/指标在 SDK 重试预算耗尽后丢失（应用日志文件仍是事故证据，这是 markpost 接受过的取舍，如今也是我们的）；ERROR 日志速率规则顶着数据源瑕疵以暂停状态上线，而不是盲目绕过；基础设施侧预配置（NAS 文件、kuma 监控项）活在本仓库门禁之外，`docs/monitoring.md` 是同步点，姊妹项目也正是这样运营它的栈。对节奏敏感的行为（静默运行告警、心跳保留期）现在是应用导出的 gauge 与预配置规则之间的契约；未来任何调度器变更都必须继续导出预期间隔 gauge，否则告警退化为无数据静默——遥测断流规则同样盯守这种失效模式，因为各 gauge 搭的是同一条常在指标流。
