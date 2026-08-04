# 16 · 命名规范

本文是贯穿全设计的命名体系统一规范。原则:**动词原形、集合复数、领域术语统一、避免同义词混用、避免缩写、遵循 Python/社区惯例**。

## 核心动作动词(消除 check/run/track/sync 混用)

| 场景 | 统一动词 | 理由 |
|---|---|---|
| CLI 主命令(用户触发全流程) | **`run`** | `progress run` |
| Integration 的"配置→状态同步"钩子 | **`sync`** | 配置驱动的期望态同步(含 GC) |
| Integration 的"实际拉取+分析+持久化"钩子 | **`run`** | 与 CLI `run` 一致 |
| Integration 的生命周期 | **`setup`/`teardown`** | 与 06 的 4 钩子一致 |
| AI 分析单个内容 | **`analyze`** | `agent.analyze(content)` |
| 通知分发 | **`dispatch`** | `dispatcher.dispatch(event)` |
| 报告生成流水线 | **`run`**(pipeline.run) | 与 CLI 一致 |

### 消除(禁用)

`check`/`check_all`/`track`(作为动词——项目名 progress 已含"追踪"义,不再用 track 作动词避免绕口)/`process`(过于宽泛)。

## 领域名词(单复数 + 一致性)

| 概念 | 统一 | 说明 |
|---|---|---|
| 插件/集成 | **integration**(单数)/ **integrations**(包/集合) | 06 定,包名 `integrations/` |
| 插件实例类 | **`XxxIntegration`** | 如 `RepoIntegration` |
| 插件唯一标识 | **`name`** | `Integration.name`(06 定) |
| 通知载荷 | **`ChannelPayload`** | 10 定 |
| 通知事件 | **`Event`**(如 `ReportEvent`) | 10 定 |
| 通知渠道 | **`Channel`** | 10 定 |
| 报告结果(CLI) | **`RunOutcome`** | 05 定 |
| 报告结果(报告) | **`ReportOutcome`** | 09 定 |
| 通知结果 | **`DispatchOutcome`** | 10 定 |
| 发送结果 | **`SendResult`** | 10 定 |
| 配置根路径 | **`state_home`** | 02 定(XDG 共识) |
| 配置分区键 | **`section`**(列名)/ **`name`**(Integration 属性值) | 03/06 定 |
| 配置 DB 种子文件 | **`config.db.toml`** | 02 定 |

## 目录/文件命名一致性

| 类型 | 规则 | 例子 |
|---|---|---|
| 业务包 | 复数名词 | `integrations/` `notifications/` `reports/` |
| 入口包 | 单数 | `cli/` `api/` |
| 配置文件 | `config.py`(领域内)/ `root.py`(核心聚合) | `cli/ai/config.py`、`config/root.py` |
| 状态模型 | `models.py`(每包自带) | `integrations/repo/models.py` |
| 插件配置 | `config.py`(每插件自带) | `integrations/repo/config.py` |
| 模板目录 | `templates/`(每包自带) | `cli/reports/templates/reports/` |
| 翻译目录 | `locales/`(每包自带) | `integrations/repo/locales/` |
| 迁移目录 | `migrations/`(每插件自带) | `integrations/repo/migrations/` |
| 基础设施/抽象 | `base.py` | `integrations/base.py`(Integration Protocol) |
| 业务编排入口 | `core.py` | `cli/core.py` |
| 生命周期管理 | `lifespan.py` | `cli/lifespan.py` |
| 结构化结果 | `outcome.py` | `cli/outcome.py` |

## 消除的同义词混用

| 概念 | 统一用 | 消除 |
|---|---|---|
| 配置 | **config** | ~~configuration~~/~~settings~~(除 pydantic-settings 类名保留) |
| 异常 | **Exception**(如 `ProgressException`) | ~~Error~~(除边界如 `ModelError`) |
| 客户端 | **client** | ~~Client~~(大写)/~~conn~~ |
| 数据库 | **db** | ~~database~~(目录 `db/`) |
| 日志 | **log/logging**(structlog) | 变量用 `logger` |
| 渲染 | **render** | ~~format~~/~~build~~(输出) |
| 事件 | **event** | ~~message~~(避免与 email 的 message 混) |

## 模型/类命名规则

- **数据模型(状态)**:单数大驼峰(`Repository`/`Report`/`Proposal`)。
- **Pydantic 配置模型**:`XxxConfig`(`GitHubConfig`/`AnalysisConfig`)。
- **结果/产出**:`XxxOutcome`/`XxxResult`(`RunOutcome`/`SendResult`/`ReportOutcome`)。
- **事件**:`XxxEvent`(`ReportEvent`/`ProposalEvent`)。
- **载荷**:`XxxPayload`(`ChannelPayload`)。
- **枚举**:大驼峰(`ContentType`/`Protocol`)。
- **Protocol/ABC**:`XxxIntegration`/`Channel`/`Renderer`。
- **上下文(生命周期 yield)**:`Components`(dataclass)。

## 函数/方法命名

- **async 动词原形**:`run`/`sync`/`setup`/`teardown`/`analyze`/`dispatch`/`send`/`render`。
- **查询/读取**:`get_*`(`get_config`)。
- **写入/设置**:`set_*`(`set_config`)。
- **发现**:`discover_*`(`discover_integrations`)。
- **加载**:`load_*`(`load_config`)。
- **初始化**:`init_*`/`setup_*`(`init_db`)。

## 常量命名

- **大写蛇形**:`GIT_TIMEOUT`/`MAX_DIFF_LENGTH`/`AI_RETRIES`/`HTTP_TIMEOUT`。
- **模块级常量**在各自领域模块内(不集中到 `consts.py` 杂物抽屉)。

## 配置项命名

- **蛇形小写**:`state_home`/`gh_token`/`webhook_url`/`max_batch_size`/`first_run_lookback_commits`。
- **TOML section 用蛇形**:`[observability.bugsink]`。
- **避免缩写**(除惯例 `url`/`http`/`api` 等)。

## 资源命名(REST)

- **集合复数**:`/reports`/`/integrations`/`/channels`。
- **单个用 id**:`/reports/{id}`/`/integrations/{name}`。
- **API 路径前缀**:`/api/v1`。
- **前端路由与 API 一致**:复数(`/reports`/`/reports/:id`)。

## 保留的现有好命名(不强行改)

- `progress`(项目名,保留)。
- `state_home`(XDG 共识)。
- `section`/`data`(config 表列名,03 定)。
- `setup`/`sync`/`run`/`teardown`(integration 钩子,06 定)。

## 命名审核清单(实现时对照)

实现任何新符号时,对照本规范:
1. 动词是否原形?是否在统一动词表内?
2. 集合是否复数?单个是否单数?
3. 是否混用同义词(如同时用 config 和 configuration)?
4. 是否避免缩写?
5. 是否遵循 Python 惯例(类大驼峰、函数蛇形、常量大写蛇形)?
6. 是否与已定命名(本表)一致?
