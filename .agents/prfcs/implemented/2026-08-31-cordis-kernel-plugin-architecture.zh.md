# PRFC: A cordis-style kernel: everything in progress becomes a composable plugin

Status: implemented

[English](2026-08-31-cordis-kernel-plugin-architecture.md) | 中文

## Problem

progress 存在一个特权核心，而且它在继续膨胀。`cli/core.py` 在一个函数里编排整次运行——producers、reports 管线、通知创作、队列、dispatcher——于是横切策略（去重、静默时段、内容预算、`scrub.py` 之外的脱敏）除了写进管线代码 nowhere 可插。CLI 与 API 各自维护一份手写 lifespan，`progress users` 的四个子命令又各自手搓第四份微型版本（裸 `init_db`/`close_db` 配对、无迁移无合并），重复着同样的顺序知识（DB 先于 config 合并、observability 先于 `aiohttp` session、退出时 drain）；一份不变量存多份，就是在等它分叉。调度完全在进程之外——容器里由 supercronic 反复跑 `progress run`——裸机与 Windows 部署因此根本没有调度能力，任何 integration 也无法声明自己的节奏（feed 轮询快于 repo 同步这一需求表达不出来）。API 的 `set_config` 写下的配置变更，要等下一个进程启动才触达任何运行中的能力。

integrations 树已经是插件架构的大半——`@register` 加 entry_points、五钩子协议、自带 migrations/templates/prompts 的自含包——但注册表是进程级单例：每个 integration 一个实例、没有依赖语义、不能运行时挂载/卸载、同一 integration 无法以不同配置跑两份。第三方能加的只有"一个 integration"，别无其他：加不了通知 channel、telemetry 后端、scheduler，也补不了对内置插件配置的 patch。

参考移植对象 deepseek-harness 在同等规模上示范了缺失的机制：cordis 是一个小内核，插件就是 `apply(ctx, config)` 加三个声明（`inject`、`provide`、`Config`），启动顺序用服务依赖表达而非顺序代码，一切注册都是可逆 effect、逆序回收，事件是唯一横向扩展点且五种派发模式是公开契约，整个应用是一棵以数据描述的组合树（行按 id 被 patch、分层叠加）——`dsh web` 与 `--profile sdk` 的差别只是 bundle 层叠加不同，没有任何特判代码。

## Decision

引入 `progress.kernel`——cordis 语义的 Python 移植，而非其 TypeScript 机制的移植。`Context` 是经 `__getattr__` 解析的服务注册表（下划线名与协议名立即抛 `AttributeError`，保证 `copy`/`pickle`/`hasattr` 的探测不会触发解析；`ServiceNotFound` 继承 `AttributeError`，属性世界观与领域世界观不打架）。类型化访问以 `ctx.get(Type)` 为主形态——类型精确、无需 stub。曾评估为 `ctx.db` 糖语法生成 `.pyi` stub，实施后放弃：模块级 stub 会替换实现模块自身的类符号、与内核内部类型冲突；`ctx.get(Definition)` 本就携带精确类型（它一直就是主形态）。插件是函数或类，带 `inject`（必需服务）、可选 `provide`、以 pydantic model 作 `Config`；`Fiber` 持有生命周期（`PENDING → LOADING → ACTIVE → UNLOADING/DISPOSED/FAILED`），在所有注入服务就绪前保持 pending，依赖实现变化时自动重载（epoch 机制）。`apply` 内的一切注册都是带逆序 async disposer 的 effect——既有的 teardown 纪律变成结构保证而非纪律约定。事件在 `EventSpec` 注册表里声明派发模式（`emit`、`parallel`、`serial`、`bail`、`waterfall`）；模式是公开契约，派发时校验。`ServiceNotFound(AttributeError)` 与运行时 `EventSpec` 注册表是 Python 侧的新设计而非机制移植——cordis 既无该异常类、也无运行时事件注册（它靠 TS 声明合并与编译期检查），后者把参考实现由 catalog 门禁保证的模式即契约原则移进内核本体。bail 与 serial 在全异步运行时里语义重合（顺序执行、首个真值短路），五个模式名保留为公开契约、bail 实现为 serial 的否决别名。`isolate` 作为内核原语一并落地（服务映射之上的 scope-label 链，同 label 即合并作用域），即便第一阶段没有任何 profile 用它——它与 `provide`/`get` 同层、携带成本极低，且是多实例部署（mirror、多 Miniflux 源）的天然扩展点。`intercept` 配置合并随同落地。

各能力变成服务，配 Definition（声明 ctx key 的抽象 `Service`）、Provider（可换实现）、Consumer 三角色——即参考实现的 seam 纪律：

| ctx key | Definition | 内置 Provider |
| --- | --- | --- |
| `ctx.config` | 分层配置 + `subscribe(ns)` | `config-db`（现有 DB config 表 + seed 合并） |
| `ctx.db` | 连接生命周期 + migrations | `db-tortoise`（aiosqlite） |
| `ctx.http` | 共享 aiohttp session | `http-shared`（注入 telemetry——顺序不变量，声明化） |
| `ctx.telemetry` | sink seam：`emit/flush/shutdown` + 脱敏 waterfall | `telemetry-otel`、`telemetry-bugsink`、`telemetry-logfile` |
| `ctx.scheduler` | `every(cron, fn) -> Disposable` | `scheduler-asyncio`（进程内；croniter、同 entry 互斥跳过、不补跑） |
| `ctx.webServer` | `register_router(r) -> Disposable` | `webserver-fastapi`（现有 `api/` 壳） |
| `ctx.ai` | 分析调用 + 全局并发信号量 | `ai-pydantic`、`ai-replay`（测试） |
| `ctx.integrations` | 实例注册表 | — |
| `ctx.notifications` | channel 注册表 + 派发 | hub 本体 + 每 channel 一个插件 |
| `ctx.i18n`、`ctx.rss`、`ctx.markdown`、`ctx.gitHub`、`ctx.gitLocal` | 工具服务 | 现有模块平移 |

组合变成数据。行（`id`/`name`/`config`/`inject`/`disabled`）存于 patch 层：包内 `base` profile 之上，`run`、`serve`、`all-in-one` 依次叠加，再叠 state_home 用户 patch、插件行与 `--patch` 调试层——即参考实现的 bundle 语义。组合工件用 TOML 而非参考实现的 YAML（tomlkit 现成、注释保序往返、操作者只面对一种语法），延迟表达式以 `_py` 内联表惯例承载（`disabled = { _py = "not ctx.config.analysis.enabled" }`）——这是对参考实现的明确偏离，求值语义则逐条一致：只在该行的注入激活后求值、`disabled` 每次挂载决策重求值、dump 原样打印不求值；求值器为受限 eval（空 builtins 加白名单），失败 fail-loud 带行 id。行纯结构：存在/禁用/注入/调度归行，一切业务配置——内置与第三方——走 DB config 表命名空间（`ctx.config` 的 `subscribe(ns)`），单一事实源保持。`config.toml` 仍是唯一的用户配置界面，其向 patch 层的翻译缩薄为结构性推导（未配 key 摘 AI 行这类），与现行种子路径重叠，无人需要面对两套配置系统。`progress --dump-config` 与 `progress inspect` 打印生效树、fiber 状态与精确的缺失服务名，对从未激活的行 fail-loud——参考实现的启动诊断，照搬。

`core.run` 管线变成一个薄的 runner 插件加一个事件目录：`run/started`（emit）、`integration/pre-run`（waterfall——策略可拒绝）、逐 integration 的 sync/run、`integration/post-run`（parallel）、`report/assemble`（waterfall——AI 标题/摘要、预算、i18n 挂这里）、`report/generated`（emit——持久化、MarkPost、RSS 监听）、`notification/build`（serial——各 integration 仍是自己通知的唯一作者，契约从钩子变成事件语义）、`notification/dispatch`（parallel）、`run/completed`（emit）。触发粒度为流式：三族事件在各自主体完成时逐个触发，等价于现行 T9 流式语义（先完成的集成先出报告先派发）；屏障式消费（汇总后发）以累积型策略监听实现，反向不可——这是选流式的决定性理由。`notification/build` 的 payload 携带累积器、由目标 integration 填写，唯一作者契约以此保持；serial 语义为每次 dispatch 内顺序、首个真值短路，并发 dispatch 彼此不互斥（与现状等价，目录写明，不做全局排序的虚假承诺）。runner 插件以后台任务模式承载管线：apply 注册后即返回、fiber 正常 ACTIVE，管线任务经 effect 取消。

热更新按层给出明确承诺。L0：`set_config(ns)` 经 config 服务 notify 触发相关行的延迟表达式重求值，变化的行走 `fiber.update()`——`internal/update` waterfall、原位重启——并经 epoch 级联其注入者：行级精准重载而非整树重建（不注入易变节的重服务不动），channel 或语言变更由此在运行中的 serve 上实时生效。L1：组合变更是显式信号触发的重组上的事务性 diff——SIGHUP、扩展后的 `POST /config/reload`、`progress plugin` 命令自动触发；不做后台文件监视（容器信号原生、bind mount 下 inotify 不可靠，此为对参考实现的偏离）——diff 先全部创建、再移除陈旧、任一失败整体回滚；挂载/卸载一个已安装的插件永不重启，依赖驱动的 fiber 让两侧自动正确。L2：模块级替换仅限插件包、走换代式 fresh import（每代一个新模块名；`importlib.reload` 被禁止——新类对象会打断 `isinstance` 并搁浅模块单例），默认关闭、`--dev-plugin-watch` 显式开启（与参考实现自带实践一致：其基础 bundle 中 hmr 行默认 disabled）；框架面变更回退整进程重启。L3：安装新插件是进程外命令（`progress plugin add` 以 `uv --target state_home/plugins --no-deps` 装入、追加到 `sys.path` 尾部使插件解析宿主内核——插件不得声明 progress 为依赖，progress 未发布 PyPI 的事实即参考实现的 shared-cordis 保证），此后激活只是 L1。`serve` 与 `all-in-one` 跑 live；`run` 一次性、只在启动时组合。

迁移分四个阶段落地，每阶段先做到行为等价再进下一阶段，整个计划零 DB schema 变更（config 表是 KV JSON，回退任一阶段即 revert PR 序列、无数据牵连）：(1) 内核 + 双 lifespan 合一——`runtime/` 包承载九个服务 entry（db/config/telemetry 三后端/auth/i18n/git-proxy/http），`compose_base()` 成为唯一顺序知识，CLI 与 API 启动同一棵组合树，`users` 的四份手搓 bootstrap 一并收编，这是第一个验收场景、也是风险最低的一个；`http` 注入 `telemetryOtel` 点名 OTel instrumentor 的武装顺序（seam 化后唯一不能靠 inject 推导的依赖）；(2) 管线事件化，`@register` 保留为翻译成插件行的兼容 shim、integration 配置仍由实例从 DB 节自加载，第三方 entry_points 无感，遗留聚合路径（`run_notifications` 族）连同其测试删除重写；(3) notifications/telemetry/AI/scheduler 的 seam 化——telemetry 为 hub 型多后端、脱敏 waterfall 以 `scrub.py` 为最内层默认处理、`metrics.py` 函数面不动；auth 下沉进 base 树（超出等价的修复：纯 cron 部署首启即 bootstrap，幂等）；scheduler 落 croniter 服务面；(4) 组合文件、进程内调度（`scheduled-run` 消费者 + `schedule.cron` 配置节 + supercronic 退场——`scheduler-supercronic` provider 由此从服务表删除：验收已要求容器不依赖 supercronic，进程内跑通后无场景需要应用反向生成 crontab）、inspect/dump、L2/L3（L2 以换代导入原语加 stdlib 轮询 watcher 交付——不引入 fs-event 依赖——范围限第三方插件包）。AI 侧调用点零迁移：模块级 `run_extraction` 经活动 `ctx.ai` 指针路由（与 telemetry 同款漏斗），既有按模块 patch 的测试不受影响；`Components.ai` 仍由 shim 填充交付。serve 树自身挂载 integrations + runner + scheduled-run 行，serve 即 all-in-one 形态（`run` 保持一次性子集）。`users` 收编后随 db entry 附带跑 `migrate_config_data`，属安全超集，记录为有意偏差。刻意不移植并在此记录重启触发条件：浏览器端 cordis 树与 `dsh.client` combo bundle（progress 是单产品 SPA、无第三方 UI 生态；schema 驱动的设置页与 OpenAPI→`schema.ts` 契约链已覆盖需求——只取 settings-as-data 一块）；typert 远程层（progress 的 API 面是静态、产品所有的，恰是 FastAPI+OpenAPI 的最佳场景）；框架模块 HMR（即上文 L2 的限制）。

## Alternatives considered

**采用现成 Python 插件机制——pluggy、纯 entry_points、或 dependency-injector 一类 DI 容器。** 它们输了：pluggy 是钩子收集器，没有服务注册表、没有生命周期、没有可逆 effect；entry_points（已在用）只解决发现问题；DI 容器在启动期装配单例，但没有"fiber 等待依赖、依赖变化时重载、注册自动回卷"的概念。它们都给不出组合即数据与派发模式契约，而价值恰恰在那里。

**整体移植 cordis，包括 Proxy 拦截与 TypeScript 声明合并。** 它输了：声明合并在 Python 没有对应物，编译期体验无论如何带不过来；运行时语义却能干净地落在 `__getattr__`、pydantic 与 asyncio 上（async disposer 在 Python 里比 JS 更自然），机制在这里买不到任何东西。类型体验改为原生重建——`ctx.get(Type)` 精确类型 + 既有 drift-gate 模式下的生成 stub。

**描述符（配元类安装服务 slot）替代 `__getattr__` 解析。** 它输了：服务命名空间是运行时开放的注册表，而描述符是类体内的静态声明——每加一个服务都要在 import 期改 `Context` 类（import 顺序耦合，正是内核要消灭的全局状态气味），且类型检查器不执行运行时 setattr，承诺的类型收益仍需静态生成。第三方服务将永远沦为二等公民。

**保持渐进：精简 `core.run`、把两份 lifespan 提成一个共享函数、维持现有架构。** 它输了：这是治症状——共享 lifespan 函数仍靠手写编码顺序，调度仍在进程外，配置仍是冷的，integration 注册表仍是跑不了双实例的单例，第三方仍只有一个扩展点。代价与阶段 1+2 相当，上限却封死在"更整洁的单体"。

**现在就移植浏览器插件树（`dsh.client` combo bundle、SSE HMR、slots）与 typert RPC 层。** 目前输、并非永远输：两者都是为了让第三方把 UI 与类型化 RPC 送进运行中的宿主而无需重建其前端——那是发行版生态的问题，progress 没有。重启触发条件：某第三方 integration 需要自定义报告组件（先用服务端 widget descriptor，那是数据）；或外部 agent 需要程序化驱动 progress（那是 sdk 式 profile 插件，不是 typert）。

## Consequences

以下验收条目已由测试套件落实：

内核单测覆盖并通过：effect 逆序回收与逐 disposer 异常隔离；pending→激活时序；provider 重载级联到依赖者；waterfall 否决与 serial 短路；isolate 遮蔽与作用域合并；`update()` 热重载；表达式求值推迟到注入就绪之后。CLI `run` 与 API `serve` 启动同一棵组合树，`cli/lifespan.py` 与 API lifespan 的顺序知识被删除（ASGI 钩子本身保留为约 5 行的 boot shim），`progress users` 的手写 bootstrap 收编为同一棵树的子集。一次 `set_config` 写入可观察地触达运行中的 serve 而无需重启（channel 或语言变更实时生效）。一条 cron 行在 `scheduler-asyncio` 下进程内执行，容器部署不再依赖 supercronic 完成计划运行。`progress --dump-config` 与 `progress inspect` 打印带 fiber 状态的生效树，未激活的行报告精确缺失服务名并 fail-loud。组合更新是事务性的：某行激活失败会回滚同批兄弟行（有测试）。现有测试套件（`uv run pytest`）每个阶段保持全绿，经 entry_points 发现的第三方 integration 在 `@register` shim 之后无感加载。

Residual risks and their mitigations:

内核是需要自行维护的基础设施——本提案最大的单项成本，约 1200–1600 行加上等量的测试（cordis 内核核心实勘为 2409 行 TS；原估 500–800 偏乐观——fiber 的 epoch/effect/inertia 机制没有 Proxy 机制可甩、恰是要买的部分），组合加载器阶段 4 另计约 800–1200 行；缓解在于只移植语义（参考实现是每个机制的 oracle）、启动诊断与内核同阶段交付，且四阶段计划允许在任意阶段止损、落袋为安（零 DB schema 变更使回退永远是无数据牵连的 revert）。调试栈会变深；缓解是 inspect/dump 与 fail-loud 激活诊断与内核同阶段交付而非事后补——没有它们的内核是可运维性的倒退。两套配置表面可能困扰用户；`config.toml` 保持唯一用户界面、patch 层始终是部署工件，靠文档而非纪律守住。fiber 状态机的 async 重入（回收顺序、epoch 竞态）确实精妙；缓解是照搬参考实现的 epoch/inertia 设计决策而非自己发明，并对"卸载中重载"做压力测试。serial 与 bail 在参考实现的生产代码中零调用点（实勘），`notification/build` 是 serial 的首个生产使用——语义由目录文档钉住并以测试覆盖。热更新有 Python 特有的坑——effect 之外的模块级状态、无法卸载的 C 扩展、僵尸换代；缓解是 effect-only 注册契约、inspect 审计违规、L2 保持为受限制的带回退能力而非承诺。最后，团队对这一风格不熟悉是真实的；每个阶段都先落地行为等价，因此回退永远是一个有界的局部决定。
