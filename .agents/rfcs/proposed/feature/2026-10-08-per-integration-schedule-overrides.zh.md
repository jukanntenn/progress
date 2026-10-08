# RFC: 集成级调度覆盖

Status: proposed

[English](2026-10-08-per-integration-schedule-overrides.md) | 中文

## Problem

调度目前只有一条全局节奏。`core.schedule.cron` 只挂载一个 `scheduled-run` 触发器,触发时 `runner.run_once()` 一次性跑完所有已挂载的集成,因此设置 UI 能表达的最细节奏就是"整条管道每天 N 次"——数据天然变化更快的集成(feed 轮询)或更慢的集成(repo release 同步)都无法拥有自己的节奏,除非拖着其余管道一起变速。这个缺口在进程内调度器落地时就被点名——没有集成能声明自己的节奏,feed 轮询快于 repo 同步是无法表达的——而为此预留的部件如今全部就位(按条目 `every(cron, fn)` 的调度器、重启 scheduled-run fiber 的 L0 reload、免费渲染任意插件配置字段的 schema 驱动设置编辑器),缺的只是集成粒度本身。具体驱动:`feed` 目前跟随全局节奏每天跑两次,它应当每四小时跑一次。

## Proposal

### 能力就是一个约定配置字段

集成声明调度能力的方式,是在自己的 `config_schema` 模型上声明一个 `schedule_cron: str = ""` 字段——仅此而已。字段出现在 `model_fields` 中即等于能力存在:设置编辑器从 section schema 自动渲染该字段,`PUT /api/v1/config/{section}` 校验后存入集成自己的 DB section,而从未声明该字段的 schema 会在写入时拒绝这个键(`extra="forbid"`),因此未声明能力的集成零代码继承全局节奏,也不会漂移到半配置状态。五钩子 `Integration` 协议不受影响:第三方集成照常加载,接入能力只是在自己配置模型里加一个字段——正是插件布局早已承诺的自包含自治。

### 统一的 cron 校验

一个共享的、基于 croniter 的校验器为所有插件 schema 统一持有该字段的语义——一个可复用的 pydantic annotated type,接受调度器与 `expected_max_gap_seconds` 已经在解析的 5 字段 cron 方言。每个声明该字段的集成获得完全一致的校验:非法表达式在 PUT 时返回 422 且 DB 不落任何改动;DB 中已存在的非法值(schema 降级、手工编辑)在加载时降级为继承全局并记录警告,与 `strip_unknown_config_keys` 和 feed 配置加载器遵循的是同一套优雅降级惯例。

### 覆盖即独立节奏

`scheduled-run` 行在 arm 时解析每个已挂载集成的生效 cron——`schedule_cron` 覆盖值非空则用之,否则用全局 `schedule.cron`——按生效 cron 分组,每组注册一个调度条目触发 `run_once(only=<组>)`。被覆盖的集成完全离开全局组:不再搭全局 cron 的便车,没有重复报告或通知,组的节奏就是集成的节奏。section 读取发生在 fiber 的 `apply` 内(异步 DB 读),因此每次重新 arm 都读实时配置,损坏或缺失的 section 对该集成降级为继承全局。

### runner 支持子集运行

`run_once()` 增加可选的 `only: set[str]` 过滤参数作用于 producer 列表。事件载荷、报告组装、通知作者本就按集成分流,因此子集运行恰好等于今天的全量运行减去被排除的集成——不引入新的管道路径。按需的 `progress run` 保持不过滤:手动运行的含义就是"现在全跑一遍",`trackers_only` 维持现有语义。

### 热更新沿用 L0

不新增任何 reload 机制。`scheduled-run` 行本来就注入 `config`,因此任意 section PUT(全局或插件)都会触发 `composer.reload_config()` 重启该 fiber;重启时重读所有 section 并重新 arm 分组。在设置 UI 里编辑 `feed.schedule_cron` 于下一次 arm 生效,无需重启进程,与今天编辑全局 cron 的行为完全一致。

### 调度级观测

`progress.schedule.expected_max_gap_seconds` 与 `progress.pipeline.last_success_epoch` 增加调度组属性(组的 cron 与成员名),Uptime Kuma push 按组触发并使用该组的 retention——最高频的组自然主导单一 push monitor 的静默窗口。今天按无属性 gauge 除算的告警规则在同一次变更中切换为按组查询。

### feed 是第一个采用者

`FeedIntegrationConfig` 声明 `schedule_cron`,示例 `0 */4 * * *`;其余已发布的集成一概不声明,保持全局节奏。

## Alternatives considered

**协议级能力属性(在 Integration 类上标 `supports_schedule = True`)。** 覆盖值无论如何都必须存在某个配置模型里——那才是设置编辑器渲染、校验、存储的面——属性只是为一个比特引入第二真相源,而字段本身已承载全部能力。

**被覆盖的集成仍然搭乘全局 cron。** 双重调度在每次重叠时产生重复报告与通知,也背离独立节奏的目的;排除是让一个集成恰好只有一条调度的唯一语义。

**每个集成在 `setup` 里自己注册 `every(cron, ...)`。** 调度所有权散入各集成代码,没有任何一处能看见全部节奏——"全局排除已覆盖者"的分组、按组的观测、reload 重新 arm,都需要一个在 arm 时解析完整映射的消费者。

**core 配置里的集中式集成调度表。** core 将不得不了解插件名及其 schema 字段,违背 section 归插件自有的模型,也把能力藏到 schema 编辑器已经渲染的按集成设置面之外。

**多个全局 cron(`schedule.crons`)。** 仍是全管道语义:表达的是"所有东西跑得更勤",而非"feed 比 repo 同步跑得快"。

**各插件自定义 cron 方言。** 各插件自写校验会在"什么是合法表达式"上发散;一个共享校验器让 PUT 报错与加载降级保持一致。

## Acceptance criteria

- feed 未设置 `schedule_cron`:行为不变——每次全局 cron 运行都与其他集成一起包含 feed。
- feed 设置 `schedule_cron = "0 */4 * * *"`:一条专属调度每四小时触发且只跑 feed;全局 cron 运行排除 feed。
- 设置 UI 仅凭 section schema 就在 feed 分区渲染出调度字段;非法 cron 在 PUT 时返回 422 且 DB 不落任何改动。
- 通过 API 修改 `schedule.cron` 或 `feed.schedule_cron` 后无需重启进程即重新 arm(L0 reload)。
- 节奏 gauge 按组导出;告警规则按组属性查询。
- schema 缺该字段的集成继承全局节奏;向这种 section PUT 该键会校验失败。

## Risks

- 观测迁移是耦合的:两个节奏 gauge 变为带属性的序列,同一次变更必须更新按无属性序列查询的仪表盘与告警规则——它们几天前刚随生产监控交付——否则告警会静默失配。
- arm 时读取 section 让 scheduled-run fiber 在(重新)arm 时依赖 DB 状态;损坏的 section 以记录警告的方式降级为继承全局,而不是让 fiber 失败。
- L0 重新 arm 的窗口里,dispose 与 arm 之间存在一个无调度的瞬间——与今天改全局 cron 的暴露相同,受 fiber 重启边界约束。
- 多组共用一个 Kuma push URL 时,最高频组可能掩盖静默停滞的慢组;按组 monitor 需要按组的 env 配置,暂缓。
- schema 驱动编辑器把 cron 渲染为自由文本,校验是唯一护栏;专用 cron 控件可后续补充,不动这份契约。
