# 监控手册（Grafana · Uptime Kuma · 降级）

[English](monitoring.md) | 中文

本手册是 [`observability.zh.md`](./observability.zh.md) 的运维配套：在哪里查询遥测、哪一层负责哪个告警、如何验证回退有效。一个故障只有一个归属——同一层上没有信号被两处同时监视。

## 技术栈与查询入口

| 信号 | 存储 | Grafana 数据源 | 查询入口 |
|---|---|---|---|
| 指标 | VictoriaMetrics（`victoriametrics:8428`，NAS） | `victoria-metrics`（PromQL/MetricsQL） | 仪表盘 + Explore |
| 日志 | VictoriaLogs（`victorialogs:9428`，NAS） | `victoria-logs`（LogsQL） | 仪表盘（内嵌日志面板）+ Explore |
| 追踪 | Jaeger v2（`jaeger:16686`，NAS） | `jaeger` | 日志行 →「View trace in Jaeger」链接，或 Explore |

三者都由 NAS 上同一个 `otelcol-contrib` 前置承接（`192.168.5.57:4318`，bearer token 准入，fail-closed）。Grafana 位于 `http://192.168.5.57:3000/`（内网）/ `https://grafana.bytehome.fun/`（公网）。日常使用：**Dashboards → progress 文件夹 → 任选一块仪表盘 → 时间范围（右上角）+ env 下拉框（左上角）**。Explore 仅用于临时排查。脚本与 agent（智能体）可直接查询各存储的 HTTP API（VictoriaMetrics `/api/v1/query`、VictoriaLogs `/select/logsql/query`、Jaeger `/api/traces`）。

环境隔离靠同一套仪表盘加一个基于标准 `deployment.environment.name` 属性的 `env` 变量实现，绝不按环境复制一套。VictoriaLogs 数据源带有派生字段链接（`trace_id` → Jaeger），因此日志与追踪处处可以互相跳转，仪表盘内也不例外。

## 仪表盘（`progress` 文件夹，NAS 上以文件预配置）

| 仪表盘 | 回答的问题 |
|---|---|
| progress Overview | 服务是否健康、是否在交付？运行结果、报告/通知计数、紧凑的 HTTP RED、距上次成功的时长与预期间隔的对照、WARN+ 日志流 |
| progress HTTP | UI/API 服务得好不好？按路由的 QPS / p95 / 状态码 / 5xx；运行期间的 SQLite 争用会在这里现形 |
| progress Pipeline & Integrations | 核心工作负载干完活了吗？各集成的结果与耗时、AI（人工智能）/git 依赖健康度、数据质量劣化计数（静默失败的早期预警） |
| progress Runtime & Telemetry | 进程与遥测管线本身还好吗？内存/CPU/线程、锚点序列新鲜度、ERROR 日志压力与日志流 |

预配置文件位于 NAS 的 `~/docker/grafana/provisioning/`（`dashboards/json/progress/*.json`、`progress.yml`、`alerting/rules-progress.yaml`，以及共享的 `contact-points.yaml` / `policies.yaml`）。它们是基础设施侧的交接材料，刻意不放进本仓库；本手册与对应 RFC 是其内容的仓内记录。

## 告警归属

| 层 | 归属 | 信号 |
|---|---|---|
| 边缘/源站可用性 | **Uptime Kuma**（`192.168.5.50:3001`） | Web UI 探针、`/readyz` 探针（能感知数据库）、流水线心跳（push） |
| 主机资源 | **Beszel**（既有设施，不在本文范围） | 磁盘/内存/CPU/agent 掉线 |
| 应用、业务、流水线、遥测管线 | **Grafana 托管告警**（`progress` 文件夹，`progress-app` 组，1m） | 下表规则 |

规则清单（`rules-progress.yaml`，标签带 `service: progress`；通知策略按该标签路由到 `progress-alerts` contact point → 邮件 → mailrise → 飞书，按 `alertname` + `deployment.environment.name` 分组）：

| 规则 | 级别 | 触发条件 |
|---|---|---|
| pipeline run failed | 警告 | 30 分钟内出现任意一次运行失败（5 分钟防抖） |
| pipeline failing repeatedly | 严重 | 6 小时内失败 ≥2 次 |
| pipeline silent | 严重 | 在应用自报的预期最大间隔 ×1.5 + 30 分钟宽限内无成功；设计上与运行节奏无关 |
| integration failures occurring | 警告 | 30 分钟内出现任意一次集成失败（按集成分实例） |
| AI call failures occurring | 警告 | 30 分钟内出现任意一次 AI 调用失败（按模型分实例） |
| git op failures occurring | 警告 | 30 分钟内出现任意一次 git 操作失败（按命令分实例） |
| notification failures occurring | 警告 | 1 小时内有报告通知发送失败 |
| HTTP 5xx occurring | 警告 | 10 分钟内 5xx 响应 >2 次 |
| telemetry gap (staging / production) | 严重 | 锚点序列 `process.memory.usage` 10 分钟未出现，说明应用→collector→存储链路已断 |
| data-quality degradation | 警告 | 1 小时内回退/解析/diff/未匹配事件 >5 起；报告已劣化但仍能产出 |
| ERROR log rate high | 警告 | 5 分钟窗口内每分钟 ERROR 日志 >15 行；预配置为**暂停**状态：victoriametrics-logs 数据源输出整数帧（上游已知瑕疵） |

两个环境各有一条遥测断流规则；对不产遥测的环境设规则会永久触发，因此生产规则与生产部署同步落地。

## Uptime Kuma 监控项

每环境一个组（`progress · staging`、`progress · production`），各叶子监控项带 `env:` / `service:progress` / `layer:` 标签：

| 监控项 | 类型 | 含义 |
|---|---|---|
| `progress · stg · web ui (origin)` | HTTP GET `/` | 从外部可达 Caddy + SPA + 代理链 |
| `progress · stg · readiness (origin)` | HTTP GET `/readyz` | 同上且数据库能应答（`SELECT 1`）；两项都红 = 进程/主机问题，仅此项红 = 数据库问题 |
| `progress · {stg,prod} · pipeline heartbeat (push)` | push | serve 进程推送每次运行的判定结果（`status=up/down`、msg）；推送窗口取监控项的心跳间隔（86400 秒）——尽力而为，kuma 的静默检测是兜底 |

推送 URL 是 vault secret（`kuma_push_url`，纯 URL——查询串由应用自行追加）。`PROGRESS_KUMA_PUSH_URL` 为空则完全禁用推送。

已知结构性风险，如实记录：kuma 单实例跑在 oect 主机上；该主机一死，可用性监控即全盲，Grafana 的遥测断流规则与 Beszel 是交叉校验。迁移/双开 kuma 属基础设施演进，不是 progress 的问题。

## 降级演练（接线变更后执行）

1. **collector 中断**：在 NAS 上执行 `docker stop otelcol`。预期：progress 容器不受影响（不重启、不卡死）；`progress.log` 本地继续增长，其中 SDK 导出失败记为 WARNING；`docker start otelcol` 后数分钟内遥测恢复，无需重启 progress；遥测断流告警触发过并已恢复。
2. **模式回退**——在未设置 `progress_otlp_token` 的情况下重新部署：compose 守卫丢弃 OTLP 块，应用重新写 `data/observability/*.jsonl`（文件模式是默认行为，不是代码路径变更）。
3. **心跳关闭**——以空的 `kuma_push_url` 部署：调度器记一条日志后跳过推送，无报错。
4. **阈值调优**：初始阈值（5xx >2、数据质量 >5 起/小时、ERROR >15 行/分钟）只是初判值；在 NAS 上的 `rules-progress.yaml` 中调整，并把变更记录到本手册。

## 排查路径

症状 → 面板 → 日志 → 追踪：打开相关仪表盘，读 stat 行（是什么），扫内嵌日志面板（哪个组件，看 `event` 字段），在可疑行上点「View trace in Jaeger」（为什么，逐 span 耗时）。可用性类症状则从 kuma 入手。带完整堆栈的错误无论如何都在 Bugsink（`http://192.168.5.50:8770/`）里；它是独立的第四通道。
