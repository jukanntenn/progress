# RFC: 集成级调度覆盖

Status: implemented

[English](2026-10-08-per-integration-schedule-overrides.md) | 中文

## Problem

调度目前只有一条全局节奏。`core.schedule.cron` 只挂载一个 `scheduled-run` 触发器,触发时 `runner.run_once()` 一次性跑完所有已挂载的集成,因此设置 UI 能表达的最细节奏就是"整条管道每天 N 次"——数据天然变化更快的集成(feed 轮询)或更慢的集成(repo release 同步)都无法拥有自己的节奏,除非拖着其余管道一起变速。这个缺口在进程内调度器落地时就被点名——没有集成能声明自己的节奏,feed 轮询快于 repo 同步是无法表达的——而为此预留的部件当时全部就位(按条目 `every(cron, fn)` 的调度器、重启 scheduled-run fiber 的 L0 reload、免费渲染任意插件配置字段的 schema 驱动设置编辑器),缺的只是集成粒度本身。具体驱动:`feed` 跟随全局节奏每天跑两次,它应当每四小时跑一次。

## Decision

### 能力就是一个约定配置字段

集成声明调度能力的方式,是在自己的 `config_schema` 模型上声明一个 `schedule_cron: str = ""` 字段——仅此而已。字段出现在 `model_fields` 中即等于能力存在:设置编辑器从 section schema 自动渲染该字段,`PUT /api/v1/config/{section}` 校验后存入集成自己的 DB section,而从未声明该字段的 schema 会在写入时拒绝这个键(`extra="forbid"`),因此未声明能力的集成零代码继承全局节奏,也不会漂移到半配置状态。五钩子 `Integration` 协议不受影响:第三方集成照常加载,接入能力只是在自己配置模型里加一个字段——正是插件布局早已承诺的自包含自治。

### 统一的 cron 校验

`progress.utils.cron` 为所有插件 schema 持有该字段的语义:`CronExpression`,一个可复用的 pydantic annotated type,接受调度器与 `expected_max_gap_seconds` 已经在解析的 5 字段 cron 方言(空值继承;六字段秒级形式被拒绝)。每个声明该字段的集成获得完全一致的校验:非法表达式在 PUT 时返回 422 且 DB 不落任何改动;DB 中已存在的非法值(schema 降级、手工编辑)在 arm 时降级为继承全局并记录警告,与 `strip_unknown_config_keys` 和 feed 配置加载器遵循的是同一套优雅降级惯例。

### 覆盖即独立节奏

`scheduled-run` 行在 arm 时解析每个已挂载集成的生效 cron——`schedule_cron` 覆盖值非空则用之,否则用全局 `schedule.cron`——按生效 cron 分组(`resolve_schedule_groups`),每组注册一个调度条目触发 `run_once(only=<组>)`。被覆盖的集成完全离开全局组:不再搭全局 cron 的便车,没有重复报告或通知,组的节奏就是集成的节奏;覆盖值恰好等于全局表达式时并入全局组而非复制一条。section 读取发生在 fiber 的 `apply` 内(异步 DB 读),因此每次重新 arm 都读实时配置,损坏或缺失的 section 对该集成降级为继承全局。只要全局 cron 有值,全局组就会被布防——即使组内没有成员——以保持覆盖功能落地前的空转行为。

### runner 支持子集运行

`run_once()` 接受可选的 `only` 过滤参数作用于 producer 列表;过滤器中的未知名字记警告并被忽略。事件载荷、报告组装、通知作者本就按集成分流,因此子集运行恰好等于全量运行减去被排除的集成——不引入新的管道路径。按需的 `progress run` 保持不过滤:手动运行的含义就是"现在全跑一遍",`trackers_only` 维持现有语义。

### 热更新沿用 L0

不新增任何 reload 机制。`scheduled-run` 行本来就注入 `config`,因此任意 section PUT(全局或插件)都会触发 `composer.reload_config()` 重启该 fiber;重启时重读所有 section 并重新 arm 分组。在设置 UI 里编辑 `feed.schedule_cron` 于下一次 arm 生效,无需重启进程,与编辑全局 cron 的行为完全一致。

### 调度级观测

`progress.schedule.expected_max_gap_seconds` 与 `progress.pipeline.last_success_epoch` 按调度组各导出一个观测点,属性携带组的 cron 与成员名;Uptime Kuma push 按组触发并使用该组的 retention——最高频的组自然主导单一 push monitor 的静默窗口。

### feed 是第一个采用者

`FeedIntegrationConfig` 声明 `schedule_cron`,示例 `0 */4 * * *`;其余已发布的集成一概不声明,保持全局节奏。

## Testing

`tests/unit/test_cron_validator.py` 钉住方言:空值通过,五字段表达式通过,四字段/六字段、越界分钟与乱串拒绝,annotated type 在模型内拒绝非法值。`tests/unit/runtime/test_scheduled_run.py` 钉住分组:纯函数 `resolve_schedule_groups`(全局组成员、覆盖排除、同表达式合并、全局为空时无组且仅保留覆盖组),boot 级布防(空转行、全局 cron、env 回退、覆盖布防独立 `scheduled-run[<cron>]` 条目且全局条目排除该集成、覆盖等于全局时并入、无效存储值降级),以及先前的节奏数学与 kuma URL 构造。`tests/component/test_core_orchestration.py` 钉住 runner 子集(`only` 只跑指定集成;未知名字被忽略),`tests/component/test_config.py` 钉住写入路径(`PUT /api/v1/config/feed` 非法 cron 返回 422 且不落库;合法 cron 经 section 往返)。

## Alternatives considered

**协议级能力属性(在 Integration 类上标 `supports_schedule = True`)。** 覆盖值无论如何都必须存在某个配置模型里——那才是设置编辑器渲染、校验、存储的面——属性只是为一个比特引入第二真相源,而字段本身已承载全部能力。

**被覆盖的集成仍然搭乘全局 cron。** 双重调度在每次重叠时产生重复报告与通知,也背离独立节奏的目的;排除是让一个集成恰好只有一条调度的唯一语义。

**每个集成在 `setup` 里自己注册 `every(cron, ...)`。** 调度所有权散入各集成代码,没有任何一处能看见全部节奏——"全局排除已覆盖者"的分组、按组的观测、reload 重新 arm,都需要一个在 arm 时解析完整映射的消费者。

**core 配置里的集中式集成调度表。** core 将不得不了解插件名及其 schema 字段,违背 section 归插件自有的模型,也把能力藏到 schema 编辑器已经渲染的按集成设置面之外。

**多个全局 cron(`schedule.crons`)。** 仍是全管道语义:表达的是"所有东西跑得更勤",而非"feed 比 repo 同步跑得快"。

**各插件自定义 cron 方言。** 各插件自写校验会在"什么是合法表达式"上发散;一个共享校验器让 PUT 报错与加载降级保持一致。

## Consequences

- 声明了 `schedule_cron` 的集成零前端成本获得自己的节奏:设置编辑器从 section schema 渲染字段,写入路径负责校验、存储与实时重新布防。`feed` 每四小时运行,其余管道保持全局节奏。
- 两个节奏 gauge 现在是带属性的序列;仪表盘与告警规则必须按 `schedule`/`integrations` 属性查询,不能再假设单一无属性的管道节奏——可观测性文档已在同一次变更中更新,既有的按无属性 gauge 除算的告警规则在下次触碰时需要补上属性过滤。
- arm 时读取 section 让 scheduled-run fiber 在(重新)arm 时依赖 DB 状态;损坏的 section 以记录警告的方式降级为继承全局,而不是让 fiber 失败。
- L0 重新 arm 的窗口里,dispose 与 arm 之间存在一个无调度的瞬间——与改全局 cron 原本的暴露相同,受 fiber 重启边界约束。
- 多组共用一个 Kuma push URL 时,最高频组可能掩盖静默停滞的慢组;按组 monitor 需要按组的 env 配置,继续搁置。
- schema 驱动编辑器把 cron 渲染为自由文本,校验是唯一护栏;专用 cron 控件可后续补充,不动这份契约。
