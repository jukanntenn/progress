# feed · RSS 资讯摘要跟踪

> 本规范定义 feed integration 的**完整业务行为**。读者对象:实现者、审查者、后续维护者。规范即验收标准——每一条"必须"都应对应可通过的测试。
>
> 本 integration 源自独立的 feeber 项目(从 Miniflux 未读条目生成 AI 摘要),重写为 progress 的内置 integration。这是全新设计,不保留 feeber 的任何历史包袱,不与 feeber 兼容。

## 1. 业务概述

feed integration 对接一个外部 **RSS 阅读器服务(Miniflux)**,周期性地拉取其中的**未读条目**,按订阅源(feed)分组,为每个 feed 调用 AI 生成聚合摘要,渲染为一份"RSS 资讯摘要报告",经 reports pipeline 聚合落库 + 可选 MarkPost 发布,并派发一次聚合通知。

**核心价值**:把 Miniflux 里积压的未读资讯,自动压缩成 AI 摘要,让用户用一份报告快速了解多个订阅源的最新动态,而非逐条阅读。

### 数据源:Miniflux

Miniflux 是一个极简的自托管 RSS 阅读器,提供 REST API。feed integration 只对接 Miniflux 一个数据源,通过官方同步 Python client 访问。

**为什么不直接抓 RSS feed**:RSS 聚合(订阅管理、抓取调度、去重、已读状态)是 Miniflux 的职责,progress 不重复造这个轮子。feed integration 只消费 Miniflux 已聚合好的"未读条目",专注做 AI 摘要。

### 业务流程

1. **生命周期**(`setup`/`sync`/`run`/`build_notification`/`teardown`):遵循 spec 06 的统一 integration 契约。
2. **拉取**(`run` 内):从 Miniflux 拉取全部未读条目,按 feed 分组。
3. **去重**(`run` 内):用每个 feed 的 `last_entry_id` 水位过滤掉已处理过的条目。
4. **AI 分析**(`run` 内):为每个有新条目的 feed 调用一次 AI,生成该 feed 的聚合摘要 + 每条目的要点。
5. **产出报告段**(`run` 内):每个有新条目的 feed 产出一个 `ReportSection`。
6. **checkpoint 推进**(`run` 内):分析完成后,把每个 feed 的 `last_entry_id` 推进到本批最大值。
7. **聚合与发布**:报告段经 reports pipeline 统一聚合 + AI 生成报告标题/摘要 + 落库 + 可选 MarkPost 批量发布(spec 09)。
8. **通知**(`build_notification`):一次 run 产出**一个**聚合 `NotificationEvent`,经 dispatcher 派发到启用的通道(spec 10)。

### 关键业务规则

1. **数据源驱动,非配置驱动**——feed integration 追踪哪些 feed **完全由 Miniflux 决定**(Miniflux 里订阅了什么就追踪什么)。这与 repo/changelog/proposal(配置里显式列追踪对象)根本不同。因此 `sync` 是 no-op(§4)。
2. **去重靠 `last_entry_id` 水位**——每个 feed 维护一个单调递增的 entry id 水位,下次只处理 `id > 水位` 的条目。Miniflux 的 entry id 全局单调递增。
3. **per-feed AI 分析**——每个 feed 一次 AI 调用(不是一个条目一次),产 feed 级摘要 + 逐条目要点。
4. **跨 feed 报告标题/摘要复用 pipeline**——feed 自己**不**做全局 title/summary AI 抽取,复用 reports pipeline 的统一 `generate_title_summary`(spec 09)。这消除了 feeber 原设计的第二轮全局 AI 调用。
5. **AI 失败 per-feed 降级**——某 feed 的 AI 分析失败,该 feed 仍进报告(摘要标记降级),不影响其它 feed。
6. **checkpoint 在分析后立即推进**——`run` 内拉取→过滤→分析→建报告段后、return 前,推进 `last_entry_id`。语义是"这些条目已被 feed integration 处理(分析完)"。报告落库/发布是下游 pipeline 的职责,与去重解耦。
7. **零配置降级**——`base_url` 为空时,feed integration 降级禁用(返回空 RunResult + warning),不报错退出,不影响其它 integration。

---

## 2. 数据模型

### `FeedTracker`(表 `feed_trackers`)

每个 Miniflux feed 一行,记录该 feed 的去重水位和展示元数据。

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `feed_id` | BigIntField | **unique** | — | Miniflux feed id;**身份键**(upsert/GC/dedup 都基于它) | — |
| `title` | CharField(512) | required | — | feed 标题(展示用,可变;随 Miniflux 元数据更新) | — |
| `site_url` | CharField(1024) | nullable | None | feed 站点 URL(展示用,可变) | None:Miniflux 未提供该 feed 的站点 URL |
| `last_entry_id` | BigIntField | nullable | None | 该 feed 已处理的最高 entry id(**去重水位**) | None:该 feed 从未成功处理过条目(首次见到这个 feed) |
| `last_check_time` | DatetimeField | nullable | None | 上次处理时间戳 | None:该 feed 从未执行过处理 |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | `updated_at` 由 `BaseModel` 在每次 save 时自动刷新 | — |

### 字段语义精确说明

**`feed_id` 是身份键**:
- 来自 Miniflux,在 Miniflux 内稳定不变。
- feed integration 不允许用户在 config 里指定 feed 列表(§1 规则 1)——`FeedTracker` 行的增删完全由 `run` 时 Miniflux 实际返回的 feeds 决定。

**`last_entry_id`(水位)的推进规则**:
- 仅当某 feed 在本次 run 中**有新条目被分析完成**时,水位推进到这些新条目中的最大 entry id。
- 无新条目(水位已覆盖全部未读)→ 不推进水位,但仍更新 `last_check_time`。
- feed 不再存在于 Miniflux → 整行删除(GC,§4.2),水位随之消失。

**`last_check_time`(处理时间戳)的盖戳规则**:
- 每次 `run` 见到该 feed(无论有无新条目)都盖戳为当前时间。
- 用于 Web UI 展示"上次同步时间"。

**为什么不建"条目快照"表**(类似 proposal 的 `Proposal` 表):
- proposal 的 `Proposal` 表承载状态机(Draft→Review→Final 的变迁),需要持久化状态用于 diff。
- feed 的条目是**一次性消费**的(未读→处理→水位推进),无状态机,去重只靠 `last_entry_id` 水位就足够。建条目快照表违反 YAGNI(spec 00 P7)。

---

## 3. 配置

### `FeedIntegrationConfig`(integration 顶层配置)

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `base_url` | str | 否 | `""` | Miniflux 实例地址(如 `https://miniflux.example.org`);空 → feed integration 降级禁用 |
| `api_key` | `SecretStr` | 否 | `""` | Miniflux API key;`base_url` 非空但 `api_key` 空 → 降级 + warning |

配置类 `extra="forbid"`:出现未定义字段时报错。配置从 DB config 表(section = `"feed"`)读取。读不到时回退全默认(空 `base_url`/空 `api_key`)——这是 zero-config 行为,feed integration 静默禁用。

### 配置示例(`config.db.toml`)

```toml
[feed]
base_url = "https://miniflux.example.org"
api_key = "MF-api-key-xxxx"          # SecretStr;GET /api/v1/config 自动脱敏为 **********
```

### 为什么 feed 配置只有这两项

feeber 原配置里的 `[database]`/`[markpost]`/`[report]`/`[analysis]`/`[notification]`/`[observability]`/`timezone` **全部删除**——这些在 progress 是核心共享基础设施(spec 02):

| feeber 原配置 | 归宿 | 理由 |
|---|---|---|
| `[database] path` | 删除 | progress 用 `state_home` 派生 DB 路径(spec 02) |
| `timezone` | 删除 | progress 已有 `[core] timezone` |
| `[markpost]` | 删除 | progress 已有 `[core.markpost]`,reports pipeline 统一发布(spec 09) |
| `[report] storage/title_prefix` | 删除 | 报告统一存 DB + 可选 markpost;title 由 pipeline AI 生成 |
| `[analysis] provider/timeout/...` | 删除 | progress 已有 `[core.analysis]`(Pydantic AI,spec 08) |
| `[notification] channels` | 删除 | progress 已有 `[core.notification.channels]`(spec 10) |
| `[observability]` | 删除 | progress 已有 `[core.observability.bugsink]`(spec 04) |

feed integration 只保留 **feed 特有的数据源凭据**(Miniflux 连接),符合 spec P5(高内聚)和 spec 02(integration 只装自己的领域配置)。

### 代码常量(不进配置,spec 02 P4)

| 常量 | 位置 | 值 | 说明 |
|---|---|---|---|
| `MAX_ENTRIES_PER_FEED` | `integrations/feed/fetcher.py` | `50` | 每次 run 每个 feed 最多处理的条目数(防止某 feed 积压刷屏) |

---

## 4. 插件生命周期

### `setup`

接收共享依赖(`Components`:CoreConfig + 共享 aiohttp ClientSession)。从 DB 读取 `FeedIntegrationConfig`;解析失败时回退默认并记录 warning。

若 `base_url` 和 `api_key` 都非空 → 创建 `MinifluxClient`(§9);否则 `self._client = None`(降级)。

**不在此处创建共享 ClientSession**——session 由上层 lifespan 管理,`MinifluxClient` 内部用 asgiref `sync_to_async` 桥接同步 miniflux client(§9.2),不直接用 aiohttp session。

### `sync` —— **no-op(数据源驱动)**

```python
async def sync(self) -> SyncResult:
    return SyncResult()  # 空:created=0, updated=0, deleted=0
```

**feed 的 `sync` 是空操作**,返回空 `SyncResult`。理由:

- repo/changelog/proposal 的 `sync` 把 config 里的追踪对象列表同步到状态表。
- feed **没有配置驱动的追踪列表**——追踪哪些 feed 完全由 Miniflux 决定(§1 规则 1)。
- `FeedTracker` 行的增删改发生在 `run` 内(§4.2),由 Miniflux 实际返回的 feeds 驱动。

这是诚实反映"数据源驱动"本质的设计。`sync` 的触发时机仍是 `run` 流程开始时(`setup → sync → run`,spec 06),只是 feed 的 sync 不做任何事。

### `run(*, concurrency: int = 1) -> RunResult`

完整执行流程(详见 §5):

1. **降级检查**:若 `self._client is None`(配置不全)→ warning + 返回空 RunResult。
2. **拉取未读**:从 Miniflux 拉全部未读条目,按 feed 分组(§5.1)。
3. **过滤去重**:用每个 feed 的 `last_entry_id` 水位过滤出新条目,每 feed 上限 `MAX_ENTRIES_PER_FEED`(§5.2)。
4. **维护 FeedTracker**:upsert 当前 Miniflux feeds 的元数据(title/site_url),GC 不再存在的 feeds(§4.2)。
5. **无新条目短路**:若所有 feed 都无新条目 → 返回空 reports(不产报告,不推进水位)。
6. **per-feed AI 分析**:对每个有新条目的 feed 调一次 AI,生成 `FeedAnalysis`(§6)。失败 per-feed 降级(§5.4)。
7. **建报告段**:每个有新条目的 feed 产出一个 `ReportSection`(§7)。
8. **推进水位**:把每个 feed 的 `last_entry_id` 更新为本批新条目的最大 entry id(§5.3)。
9. **返回** `RunResult(name="feed", reports=[...], events=[])`。`events` 始终为空(feed 不产业务事件,§8)。

**错误聚合**:
- Miniflux 连接失败 → 整体 `status="failed"`,错误计入 `RunResult.errors`。
- 单个 feed AI 分析失败 → 该 feed 降级(§5.4),不影响整体 status。
- 若有错误且无任何成功报告段 → `status="failed"`。

**并发**:接受 `concurrency` 参数(默认 1)。AI 调用受全局信号量约束(spec 08 `AI_CONCURRENCY=1`),所有 AI 分析被序列化;`concurrency` 仅对非 AI 工作(Miniflux 拉取)有理论意义,但 feed 拉取是单次全量调用,实际串行。

### `build_notification` —— 作者聚合通知

```python
async def build_notification(
    self, *, result: RunResult, reports: list[IntegrationReport]
) -> list[NotificationEvent]
```

接收 reports pipeline 产出的 `IntegrationReport` 列表(§7.3)。feed 一次 run 产出**一个** `report_type="feed"` 的聚合报告,因此 `reports` 列表长度为 0 或 1。

若 `reports` 为空(本次无报告)→ 返回空列表(不通知)。

否则产出**一个** `NotificationEvent`(§8):

| 字段 | 取值 |
|---|---|
| `kind` | 固定 `"feed"`(选 feed 的通知模板目录) |
| `title` | `reports[0].title`(pipeline AI 生成的报告标题) |
| `summary` | `reports[0].summary`(pipeline AI 生成的报告摘要) |
| `markpost_url` | `reports[0].markpost_url`(pipeline 发布的 MarkPost URL;未启用 markpost 时为空) |
| `data` | `{"feed_count": ..., "entry_count": ..., "feeds": [...]}`(详见 §8) |

### `teardown`

释放持有的引用(`self._client` 置 None,关闭 miniflux client 内部的 requests.Session)。共享 ClientSession 由上层 lifespan 管理,不在此关闭。

### 4.2 `FeedTracker` 维护(在 `run` 内)

每次 `run` 拉到 Miniflux feeds 后:

1. **upsert**:对每个 Miniflux feed,`update_or_create(feed_id=..., defaults={title, site_url})`。新建时 `last_entry_id=None`/`last_check_time=None`。
2. **GC**:Miniflux 里已不存在但 `FeedTracker` 里还在的 feed → 删除整行。语义:用户在 Miniflux 取消订阅 = 放弃追踪该 feed(水位随之消失;若未来重新订阅,会作为新 feed 从头处理)。

GC 不在 `sync` 里做(§4.1 已说明 sync 是 no-op),而在 `run` 内做,因为 GC 需要拉取 Miniflux 的实际 feeds 列表(外部 IO),spec 06 明确"sync 不拉取外部数据"。

---

## 5. `run` 核心算法

### 5.1 拉取未读条目

调用 `MinifluxClient.get_unread_entries()`(§9),返回 Miniflux 全部未读条目。

**拉取策略**:一次调用 `get_entries(status="unread")` 拉全部未读(不 per-feed 遍历拉),在内存按 feed 分组。理由:
- 未读总量通常可控(RSS 阅读器场景,不会积压成千上万未读)。
- 一次调用比遍历所有 feed 更简单高效。
- feeber 已验证此策略可行。

**分组**:条目按 `feed.id` 分组,每组封装为 `Feed` dataclass(含 feed 元数据 + 该 feed 的条目列表)。

### 5.2 过滤去重

对每个 feed:

1. 从 `FeedTracker` 读该 feed 的 `last_entry_id`(不存在则 None = 首次见)。
2. 保留 `entry.id > last_entry_id` 的条目(水位为 None 时保留全部)。
3. **上限截断**:按 entry id 降序排序后取前 `MAX_ENTRIES_PER_FEED`(50)条。防止某 feed 积压数百条未读时刷屏单次报告。
4. 若过滤后为空 → 该 feed 本次无新条目,跳过。

**`MAX_ENTRIES_PER_FEED` 截断的语义**:本次只处理最新的 50 条,剩余的会在后续 run 中处理(因为水位只推进到第 50 条的 id,第 51 条及以后的 id 更小……)。

**等等——这里有个微妙点**:entry id 单调递增意味着"更新的条目 id 更大"。按 id 降序取前 50 = 取最新的 50 条,水位推进到这 50 条里的最大 id(即最新那条的 id)。第 51 条及以后是更旧的条目,它们的 id 小于水位,下次会被水位过滤掉——**这些更旧的未读条目会被永久跳过**。

**这是有意的行为**(对齐 feeber):feed 报告的定位是"最新动态速览",不是"完整归档"。积压过久的旧条目跳过是合理的。若用户想完整处理,应在 Miniflux 里先标记为已读/清理积压。

### 5.3 推进水位

分析完成(成功或降级)后,把每个 feed 的 `last_entry_id` 推进到本批处理条目的**最大 entry id**。

**盖戳规则**:
- 有新条目被处理 → 水位推进到最大 entry id + `last_check_time` 盖戳。
- 无新条目 → 水位不变,`last_check_time` 仍盖戳(记录"这次检查过")。

水位推进在 `run` return 前完成(§1 规则 6),不依赖下游 pipeline 发布成功。

### 5.4 per-feed AI 失败降级

某 feed 的 AI 调用失败(超时、API 错误、解析失败)时:
- 该 feed **仍产出** `ReportSection`(不跳过)。
- `ReportSection.payload["summary"]` 设为降级标记文本(如 `_("AI analysis unavailable")`)。
- `ReportSection.payload["entries"]` 仍含条目元数据(title/url/published_at),但每条的 `analysis` 为空。
- 错误转发 Bugsink(spec 04)。
- 继续处理其它 feed,不影响整体 status(除非全部 feed 都失败)。

这保留报告的覆盖面(用户能看到所有 feed 有哪些新条目),只是失败 feed 缺 AI 摘要。

---

## 6. AI 分析

### 6.1 复用核心 Pydantic AI 通道

feed **不** shell-out 到 claude/codex CLI(这是 feeber 的旧做法,已被 spec 08 否定)。复用 progress 的核心 Pydantic AI 结构化抽取(`cli/ai/`,`get_agent`/`run_extraction`,spec 08)。

provider/model/api_key/language 全部来自 `[core.analysis]` 配置,feed 不重复配置(§3)。

### 6.2 per-feed 输出模型

feed 专属的 Pydantic 输出模型(定义在 feed 包内):

```python
class EntryAnalysis(BaseModel):
    entry_id: int
    analysis: str  # 该条目的 AI 要点摘要


class FeedAnalysis(BaseModel):
    summary: str  # 该 feed 的聚合摘要
    entries: list[EntryAnalysis] = []  # 逐条目要点
```

作为 `get_agent(FeedAnalysis, model=..., api_key=...)` 的 `output_type`。

**为什么不用核心的 `AnalysisResult{summary, detail}`**:feed 需要表达"一个 feed 内多条目"的结构(summary 是 feed 级,entries 是条目级),`AnalysisResult` 的扁平 `{summary, detail}` 无法承载。proposal 也定义了自己的输出语义;feed 同理需要专属模型。

### 6.3 prompt 模板

`integrations/feed/prompts/feed_analysis_prompt.j2`,接收变量:
- `feed_title`:feed 标题
- `entries`:该 feed 的新条目列表(每条含 title/url/content 片段)
- `language`:AI 输出语言(来自 `[core.analysis].language`)

prompt 要求 AI:产出该 feed 的聚合 summary + 每条目的 analysis 要点。要求 JSON 输出符合 `FeedAnalysis` schema(Pydantic AI provider 源头约束,spec 08)。

### 6.4 跨 feed 报告标题/摘要:复用 pipeline

feed **不做**自己的全局 title/summary AI 抽取。reports pipeline 的 `generate_title_summary` 阶段(spec 09)会聚合所有 integration 的 ReportSection 后,统一用 `TitleSummary` 模型生成报告级标题/摘要。

这消除了 feeber 原设计的"第二轮全局 AI 调用"(`_analyze_digest_entries`),是 progress 架构的天然简化。

### 6.5 json_repair 兜底

核心 Pydantic AI agent 的 `output_validator` 已内置 json_repair 兜底(spec 08),feed 无需额外处理。

---

## 7. 报告生成与落库

### 7.1 报告段(`ReportSection`)

每个有新条目的 feed 产出一个 `ReportSection`:

| `ReportSection` 字段 | 值 |
|---|---|
| `title` | feed 标题 |
| `content` | `""`(模板渲染失败时的兜底;正常路径靠模板渲染) |
| `payload` | 见下 |

`payload` 结构化字段(供 feed 报告模板消费):

```python
{
    "feed_title": str,  # feed 标题(= title)
    "site_url": str,  # feed 站点 URL(可为空)
    "summary": str,  # 该 feed 的 AI 聚合摘要(失败时为降级标记)
    "entries": [  # 该 feed 的新条目 + 每条 AI 要点
        {
            "title": str,  # 条目标题
            "url": str,  # 条目链接
            "published_at": str,  # 发布时间(本地时区格式化)
            "analysis": str,  # 该条目 AI 要点(失败时为空)
        },
        ...,
    ],
}
```

### 7.2 模板 `feed_report.j2`

位于 `integrations/feed/templates/feed_report.j2`,渲染一个 feed 的报告段。遵循 spec 09:
- **autoescape**:Jinja2 `select_autoescape`,用户数据(entry title/analysis)自动转义。
- **引用方向**:可引用核心 `report_base.j2` 的共享 macro(如 `footer`),不反向引用其它 integration 模板。

模板结构:
- feed 标题二级标题:`## [{feed_title}]({site_url})`(site_url 为空时无链接)
- AI summary 段落
- 条目列表:每条目标题 + 发布时间 + AI 要点(可折叠或列表形式)
- feed 之间由 reports pipeline 的 `render_aggregated` 自动用 `---` 分隔
- 结尾 `{{ footer(generation_time) }}`

### 7.3 聚合报告落库(spec 09)

报告段经 reports pipeline 聚合后,落库为一条 Report 行:

| 字段 | 值 |
|---|---|
| `report_type` | `"feed"` |
| `commit_count` | 条目总数(`sum(len(payload["entries"]) for each feed)`) |
| `title` | pipeline AI 生成的报告标题(fallback:固定默认标题) |
| `content` | 渲染后的聚合报告内容(含 AI summary 前置注入,spec 09) |

落库后经 MarkPost 发布(若 `[core.markpost] enabled=true`,spec 09),可能按 `max_batch_size` 切 batch。

**核心代码改动点**(spec 09 落库矩阵注册):
- `cli/reports/pipeline.py` 的 `_REPORT_TYPE_MAP` 加 `"feed": "feed"`。
- `cli/reports/pipeline.py` 的 `_commit_count_for` 加 feed 分支:`sum(len(s.payload.get("entries", [])) for s in sections)`。

---

## 8. 通知

### 8.1 不产业务事件

feed **不**定义自己的业务事件类型(不新增 `FeedEvent` 到 `cli/notifications/events.py`)。`RunResult.events` 始终为空。

理由:feed 不建条目快照表(§2),没有需要持久化的 per-feed/per-entry 业务事件。feed 的产出完全通过 reports pipeline + `build_notification` 的 `NotificationEvent` 表达。

### 8.2 `NotificationEvent`(由 `build_notification` 作者)

一次 run 产出**一个** `NotificationEvent`(对齐 proposal/changelog/repo 的聚合通知模式):

| 字段 | 取值 |
|---|---|
| `kind` | `"feed"` |
| `title` | `reports[0].title`(pipeline AI) |
| `summary` | `reports[0].summary`(pipeline AI) |
| `markpost_url` | `reports[0].markpost_url`(pipeline 发布的第一个 batch URL;未启用 markpost 时为空) |
| `batch_index` | `reports[0].batch_index` |
| `total_batches` | `reports[0].total_batches`(报告被切成几段;1 = 单段) |
| `data` | 见下 |

`data` payload:

```python
{
    "feed_count": int,  # 本次覆盖的 feed 数
    "entry_count": int,  # 本次条目总数
    "feeds": [  # (feed_title, entry_count) 二元组列表(渲染卡片 div 用)
        {"title": str, "entry_count": int},
        ...,
    ],
}
```

### 8.3 通知模板

位于 `integrations/feed/templates/notifications/feed/`,按通道内容类型(spec 10)。**模板内容结构 1:1 对齐 feeber 原实现**(feeber 通知是纯 Python 拼装,这里迁移到 progress 的 Jinja2 模板体系,但渲染产物等价)。

| 通道内容类型 | 文件 | 渲染规则(对齐 feeber) |
|---|---|---|
| 纯文本(console) | `plain_text.j2` | `{title}\n\n{markpost_url}`(标题 + 空行 + 单个 URL;对齐 feeber `format_console_text`) |
| HTML(email) | `html.j2` | `<h2>{escaped title}</h2><p>{escaped summary}</p><ul>每 feed `<li>{title} ({count})</li>`</ul>{可选 markpost 链接}`,autoescape + nh3 sanitize(spec 09) |
| 卡片 JSON(feishu) | `card_json.j2` | **精确对齐 feeber Feishu 卡片结构**,见 §8.3.1 |

### 8.3.1 Feishu 卡片精确结构(1:1 对齐 feeber `messages/feishu.py`)

卡片 JSON 顶层结构:

```json
{
  "config": {"wide_screen_mode": true},
  "card_link": {"url": "{{ markpost_url }}"},
  "header": {
    "template": "blue",
    "title": {"content": "{{ title }}", "tag": "lark_md"}
  },
  "elements": [
    {"tag": "div", "text": {"content": "{{ feed1.title }} ({{ feed1.entry_count }})", "tag": "lark_md"}},
    {"tag": "hr"},
    {"tag": "div", "text": {"content": "{{ feed2.title }} ({{ feed2.entry_count }})", "tag": "lark_md"}},
    {"tag": "note", "elements": [{"tag": "plain_text", "content": "报告生成工具: Progress @ {{ run_at }}"}]}
  ]
}
```

**逐元素对齐说明**(源自 feeber `notification/messages/feishu.py`):

| 元素 | feeber 原值 | feed 迁移值 | 说明 |
|---|---|---|---|
| `config.wide_screen_mode` | `true` | `true` | 不变 |
| `card_link.url` | markpost URL | markpost URL | 不变 |
| `header.template` | `"blue"` | `"blue"` | 固定蓝色,不变 |
| `header.title.tag` | `"lark_md"` | `"lark_md"` | 不变 |
| 每 feed div 内容 | `"{name} ({count})"` | `"{title} ({{entry_count}})"` | **仅 feed 标题 + 条目数,不含 AI summary**(对齐 feeber) |
| div 间分隔 | `{"tag": "hr"}` | `{"tag": "hr"}` | N 个 div 之间 N-1 个 hr(首尾无 hr) |
| footer note | `"报告生成工具: Feeber @ {时间}"` | `"报告生成工具: Progress @ {时间}"` | **"Feeber" 改为 "Progress"**(项目名语义化);时间格式 `%Y-%m-%d %H:%M:%S %Z`(本地时区) |
| footer note tag | `plain_text` | `plain_text` | 不变(非 lark_md) |

**run_at 时间戳**:本地时区格式化(来自 `cfg.timezone`),与 feeber `to_local(run_at, config.timezone)` 一致。

**0 feeds 边界**:若 `data.feeds` 为空(理论上不会,因为有报告才通知),卡片无 feed div,只有 note footer。

### 8.4 通知频率(单次,对齐 progress 架构)

feed 一次 run 产出**一个** `NotificationEvent`,**不管报告是否被 MarkPost 切成多 batch**。

**这是对齐 progress 架构的决策,非对齐 feeber**。事实核实:
- feeber 原实现是 per-batch 多次通知(`for url in urls: send_notifications(...)`,每个 batch 一次),但**不带 batch_index 标记**,每次只有 url 不同。
- progress 现有架构(spec 06/10 + 已核实 repo/proposal/changelog 源码)的 `build_notification` 钩子只接收 `IntegrationReport`(含第一个 batch url + `total_batches`),**没有任何 integration 在通知层实现 per-batch 多通知**。即便唯一有多 batch 的 repo integration,其 `build_notification` 也只产 1 个 `NotificationEvent`。

**折中**:feed 的单次 `NotificationEvent` 携带 `total_batches` 字段。报告切多 batch 时,通知只发一次(`markpost_url` 指向第一段),用户从 `total_batches > 1` 得知报告是多段的。通知模板可在 `total_batches > 1` 时渲染"(共 N 段)"提示。

**为何不扩展核心实现 per-batch 多通知**:会违背 progress 现有 3 个 integration 的统一约定,需改 `build_notification` 签名或 pipeline 产多 `IntegrationReport`,核心改动大,收益小(feed 报告因 `MAX_ENTRIES_PER_FEED=50` 上限,极少触发多 batch)。

---

## 9. Miniflux 客户端

### 9.1 选型:官方同步 client + asgiref async 桥接

使用 **Miniflux 官方 Python client**(`miniflux` PyPI 包,`miniflux/python-client` 仓库)。

**维护证据**(已 clone 到 `.local/contexts/miniflux-python-client` 核实):
- 仓库:`github.com/miniflux/python-client`
- 作者:**Frédéric Guillot**(Miniflux 创始人本人)
- 最新提交:2026-07-20(活跃维护)
- 版本:v1.1.6
- 依赖:`requests`(同步)

**为什么不用 async client**:Miniflux 官方只提供同步 client(基于 requests)。无社区维护的 async 替代品。

### 9.2 async 桥接:asgiref.sync_to_async(社区成熟库)

用 **asgiref**(`django/asgiref`,Django 官方 ASGI 库)的 `sync_to_async` 桥接同步 miniflux client 到 progress 的 async 运行时。

**维护证据**(已 clone 到 `.local/contexts/asgiref` 核实):
- 仓库:`github.com/django/asgiref`
- 最新提交:2026-07-19(活跃维护)
- `sync_to_async` 是 Django/Starlette 生态的社区标准 async↔sync 桥接原语。

**为什么用 asgiref 而非 `loop.run_in_executor` / `asyncio.to_thread`**:
- `thread_sensitive=True`(默认)将所有同步调用串行化在同一线程,对 `requests.Session` 这种**非线程安全**对象是关键保障(miniflux client 内部持有 requests.Session)。
- 自动传播 `contextvars`(OTel trace 上下文、structlog context 跨 sync 边界不丢失)。
- 社区标准,避免重复造轮子(符合 spec 00 "社区标准"原则)。
- 注:progress 现有同步库桥接(GitPython 等)用 `loop.run_in_executor(None, ...)`,feed 采用更优的 asgiref 方案;未来 progress 的其它同步桥接可逐步迁移到 asgiref 统一(本次不强行改老代码,遵循"新代码用更优方案")。

**版本约束**:`asgiref>=3.8.0`(加进 `pyproject.toml` runtime deps)。

### 9.3 `MinifluxClient`(async wrapper)

定义在 `integrations/feed/client.py`:

```python
from asgiref.sync import sync_to_async


class MinifluxClient:
    def __init__(self, base_url: str, api_key: str): ...
    async def get_unread_entries(self) -> list[RawEntry]: ...
    async def get_feeds(self) -> list[FeedMeta]: ...
    async def close(self) -> None: ...
```

- 内部持有官方 `miniflux.Client` 实例。
- 每个方法用 `await sync_to_async(self._sync_method, thread_sensitive=True)(...)` 桥接。
- `get_unread_entries()` 调 `client.get_entries(status="unread", order="published_at", direction="desc")`,解析为 `RawEntry` dataclass。
- `close()` 关闭内部 requests.Session(同样经 `sync_to_async` 桥接)。

### 9.4 认证

用 API key 认证(`miniflux.Client(base_url, api_key=...)`),这是 Miniflux 推荐方式(README 明示 "preferred method")。不支持 username/password(简化,API key 足够)。

### 9.5 超时

Miniflux client 构造时传 `timeout`。按 spec 02 P4(代码常量),用固定值 `MINIFLUX_TIMEOUT=30`(放 `client.py`,与 progress 的 `HTTP_TIMEOUT=30` 对齐)。不进配置。

---

## 10. 边界行为与 edge cases

| 场景 | 期望行为 |
|---|---|
| `base_url` 为空(零配置) | `run` 返回空 RunResult + warning,不报错 |
| `base_url` 非空但 `api_key` 空 | `setup` 降级(client=None)+ warning,`run` 返回空 |
| Miniflux 连接失败(网络/认证) | `run` 捕获异常 → `status="failed"` + errors,不推进水位 |
| Miniflux 无未读条目 | `run` 返回空 reports(不产报告),FeedTracker 不增,水位不变 |
| 某 feed 全部条目已被水位覆盖 | 该 feed 无新条目,跳过(不产 ReportSection),`last_check_time` 盖戳 |
| 某 feed 积压 >50 条未读 | 取最新 50 条,水位推进到第 50 条 id,更旧的永久跳过(§5.2) |
| 某 feed AI 分析失败 | 该 feed 降级保留(summary=降级标记),继续其它 feed,错误转 Bugsink |
| 全部 feed AI 都失败 | 各 feed 都降级保留,报告仍产出(全降级内容) |
| 用户在 Miniflux 取消订阅某 feed | 该 feed 的 FeedTracker 行被 GC 删除(§4.2) |
| 用户在 Miniflux 新订阅某 feed | 首次 run 见到 → 新建 FeedTracker(last_entry_id=None),全部未读条目视为新 |
| Miniflux feed 元数据(title)变更 | 下次 run upsert 更新 title |
| AI provider 未配置(`[core.analysis]` 空) | AI 调用走降级(返回空 summary,spec 08),各 feed summary 全降级 |
| 报告被 MarkPost 切多 batch | 通知只发一次(§8.4),NotificationEvent 携 total_batches,markpost_url 指向第一段 |
| 报告超 `max_batch_size` 且 `web.base_url` 未配 | pipeline 的 oversize stub 机制处理(spec 09) |
| e2e 无 docker 环境 | feed e2e 跳过(需 docker 跑 Miniflux);unit/component 测试不受影响(不起 docker) |

---

## 11. 并发、超时、重试

| 项 | 值 |
|---|---|
| run 并发模型 | `run(concurrency=...)`,默认 1;AI 受全局信号量序列化(spec 08) |
| async 桥接 | asgiref `sync_to_async(thread_sensitive=True)`(§9.2);thread_sensitive 保证 requests.Session 线程安全 |
| Miniflux 拉取 | 单次全量调用 `get_entries(status="unread")`,不 per-feed 遍历 |
| Miniflux 超时 | 30 秒(`MINIFLUX_TIMEOUT`,代码常量) |
| Miniflux 重试 | **无**(单次拉取,失败即 run failed) |
| AI 重试 | 由核心 Pydantic AI agent 处理(spec 08,默认校验失败重试 1 次) |
| AI 超时 | 由核心 agent 处理(`AI_TIMEOUT=600`,spec 08) |
| 单 feed AI 失败对其它 feed | **无**(per-feed 降级) |

---

## 12. 包结构(自包含,spec 06)

```
src/progress/integrations/feed/
├── __init__.py          # @register("feed") + 导出 FeedIntegration
├── config.py            # FeedIntegrationConfig (base_url + api_key SecretStr)
├── models.py            # FeedTracker
├── client.py            # MinifluxClient (async wrapper via asgiref.sync_to_async)
├── fetcher.py           # 拉取+分组+过滤 (RawEntry/Feed dataclass + 过滤算法)
├── tracker.py           # FeedIntegration (5 钩子) + FeedAnalysis/EntryAnalysis 输出模型
├── migrations/
│   ├── __init__.py
│   └── 0001_initial.py  # FeedTracker 建表
├── prompts/
│   └── feed_analysis_prompt.j2   # per-feed AI 分析 prompt
├── templates/
│   ├── feed_report.j2             # 报告段模板
│   └── notifications/feed/
│       ├── plain_text.j2
│       ├── html.j2
│       └── card_json.j2           # Feishu 交互卡片
└── locales/
    └── __init__.py     # i18n 占位(可翻译文本用 gettext,spec 11)
```

### 模块职责

| 文件 | 职责 |
|---|---|
| `__init__.py` | `@register("feed")` 注册 + 导出公共符号 |
| `config.py` | `FeedIntegrationConfig`(Pydantic,生成 JSON Schema) |
| `models.py` | `FeedTracker`(tortoise 状态模型,fat model) |
| `client.py` | `MinifluxClient`(async wrapper via asgiref.sync_to_async,封装官方同步 client) |
| `fetcher.py` | 拉取 + 按 feed 分组 + 水位过滤 + 上限截断;`RawEntry`/`Feed` dataclass |
| `tracker.py` | `FeedIntegration`(5 钩子实现)+ `FeedAnalysis`/`EntryAnalysis` Pydantic 输出模型 + ReportSection 构建 |
| `migrations/0001_initial.py` | FeedTracker 建表迁移 |

### 自动发现(无需核心改动)

以下通过 `discover_integrations()` 自动发现,只要 feed 在 registry 注册:
- models/migrations(`db/tortoise_config.py` `build_tortoise_config`)
- config schema(`config/schema.py` `get_config_json_schema`)
- 报告模板目录(`cli/reports/pipeline.py` `_collect_integration_template_dirs`)
- 通知模板目录(`cli/notifications` 镜像发现机制)

---

## 13. 核心代码改动点

spec 06 理想是"新增 integration 零改核心",但 report_type 等少量元信息是核心必须知道的。feed 落地需要 4 处核心改动(与 proposal/changelog 落地时一致):

| # | 文件 | 改动 | 必须 | 理由 |
|---|---|---|---|---|
| 1 | `integrations/registry.py` | `_BUILTIN_INTEGRATIONS` 元组加 `"progress.integrations.feed"` | ✅ | 让 `@register("feed")` 在发现时执行 |
| 2 | `cli/reports/pipeline.py` | `_REPORT_TYPE_MAP` 加 `"feed": "feed"` | ✅ | 否则 report_type fallback 到 "aggregated" |
| 3 | `cli/reports/pipeline.py` | `_commit_count_for` 加 feed 分支 | ✅ | feed 的 commit_count = 条目总数(非默认的 len(sections)) |
| 4 | `config.example.db.toml` | 加 `[feed]` section 示例 | ✅ | 配置种子文档 |

### 依赖改动

`pyproject.toml` runtime deps 加:
- `miniflux>=1.1.5,<2.0.0`(官方同步 client)
- `asgiref>=3.8.0`(async 桥接,§9.2)

**不加 markpost 依赖**——progress 已有自带的 async `MarkpostClient`(`cli/reports/markpost.py`,基于 aiohttp,不依赖 markpost PyPI 库),feed 复用它经 pipeline 发布。

### Docker 影响

**零影响**。feed 不需要任何 CLI(spec 08 已定 Docker 不装 claude/codex CLI),无系统依赖,miniflux 是纯 Python 库随 `uv sync` 安装。feeber 原 Docker 的 supercronic/npm CLI 安装全部不带入。

---

## 14. 测试矩阵(验收清单)

测试分三层(spec 15):unit/component 走 pytest(免外部服务),e2e 走真实 Miniflux docker(§15,打破 progress "免外部服务"约定的有意例外)。

### 数据模型与生命周期(component)
- [ ] `FeedTracker` 全字段建模,migration 与 model 一致
- [ ] `feed_id` unique 约束生效
- [ ] 所有 nullable 字段(site_url/last_entry_id/last_check_time)的 None 语义正确
- [ ] `setup` 读取配置,base_url+api_key 齐全时创建 client,否则降级
- [ ] `setup` 配置解析失败时回退默认 + warning
- [ ] `sync` 是 no-op,返回空 SyncResult
- [ ] `teardown` 释放引用

### run 主流程(component + e2e)
- [ ] client=None(降级)→ 空 RunResult + warning(component)
- [ ] 无未读条目 → 空 reports(e2e)
- [ ] 全部 feed 无新条目 → 空 reports,FeedTracker 不增(e2e)
- [ ] 有新条目 → 每个有新条目的 feed 产出一个 ReportSection(e2e)
- [ ] FeedTracker upsert:Miniflux 新 feed → 新建行(last_entry_id=None)(e2e)
- [ ] FeedTracker upsert:已存在 feed 元数据变更 → 更新 title/site_url(e2e)
- [ ] FeedTracker GC:Miniflux 不再存在的 feed → 删除行(e2e)

### 去重与水位(component + e2e)
- [ ] 首次见某 feed(水位 None)→ 全部未读条目视为新(e2e)
- [ ] 水位过滤:只处理 id > last_entry_id 的条目(component + e2e)
- [ ] MAX_ENTRIES_PER_FEED=50 截断:取最新 50 条(component)
- [ ] 截断后水位推进到第 50 条 id(更旧的永久跳过)(component)
- [ ] 无新条目的 feed 不产 ReportSection,last_check_time 仍盖戳(e2e)
- [ ] 有新条目的 feed 水位推进到本批最大 entry id(e2e)

### AI 分析(component)
- [ ] 复用核心 Pydantic AI 通道(get_agent/run_extraction)
- [ ] FeedAnalysis/EntryAnalysis 输出模型正确解析
- [ ] per-feed 一次 AI 调用
- [ ] AI 失败 → 该 feed 降级(summary=降级标记,entries 保留),继续其它 feed
- [ ] AI 失败错误转 Bugsink
- [ ] AI provider 未配置 → 各 feed 全降级
- [ ] prompt 模板渲染正确(feed_title/entries/language 变量)

### 报告(component + e2e)
- [ ] ReportSection.payload 结构正确(feed_title/site_url/summary/entries)(component)
- [ ] feed_report.j2 模板渲染:autoescape 生效(component)
- [ ] 模板引用核心 report_base.j2 macro(footer),不反向引用(component)
- [ ] 聚合报告落库:report_type="feed", commit_count=条目总数(e2e)
- [ ] report_type 在 _REPORT_TYPE_MAP 注册(component)
- [ ] commit_count 在 _commit_count_for 注册(条目总数,非 feed 数)(component)

### 通知(component)
- [ ] 不产业务事件(RunResult.events 始终为空)(component)
- [ ] build_notification:无报告 → 返回空列表(component)
- [ ] build_notification:有报告 → 产出一个 NotificationEvent(kind="feed")(component)
- [ ] NotificationEvent.data 结构正确(feed_count/entry_count/feeds)(component)
- [ ] title/summary/markpost_url/batch_index/total_batches 来自 pipeline 的 IntegrationReport(component)
- [ ] 三个通知模板(plain_text/html/card_json)可达且渲染正确(component)
- [ ] **Feishu 卡片(card_json)1:1 对齐 feeber 结构**(§8.3.1):wide_screen_mode + card_link + blue header(lark_md) + div"{title}({count})" 间 hr + note footer "报告生成工具: Progress @ {时间}"(component)
- [ ] console 文本 = "{title}\n\n{markpost_url}"(对齐 feeber)(component)
- [ ] 通知只发一次(单次 NotificationEvent,不 per-batch)(component)

### Miniflux 客户端(component + e2e)
- [ ] asgiref.sync_to_async(thread_sensitive=True) 桥接同步 client(component)
- [ ] get_unread_entries 调 get_entries(status="unread")(e2e)
- [ ] API key 认证(e2e)
- [ ] 30 秒超时(MINIFLUX_TIMEOUT)(component)
- [ ] close() 关闭内部 session(component)

### 配置(component)
- [ ] FeedIntegrationConfig extra="forbid"(component)
- [ ] api_key 是 SecretStr(GET /api/v1/config 自动脱敏)(component)
- [ ] base_url 空 → 降级(component)
- [ ] config schema 自动注册到 get_config_json_schema(component)
- [ ] config.example.db.toml 含 [feed] section(component)

---

## 15. e2e 测试(真实 Miniflux docker,打破 progress 约定的有意例外)

### 15.1 决策与权衡(必须记录)

feed e2e **起真实 Miniflux docker 容器**验证端到端功能。这是 progress 里**唯一**依赖 docker 的 e2e,打破了 spec 15 "e2e 免 subprocess + 免外部服务"的约定(repo/changelog/proposal e2e 全用 mock,markpost 在测试里也是 pytest-httpserver mock)。

**这是有意识的例外决策**,权衡如下:

| 维度 | 真实 Miniflux docker(采纳) | pytest-httpserver mock(否掉) |
|---|---|---|
| 验证贴近度 | **高**——验证与真实 Miniflux 2.x REST API 的真实兼容性(entry JSON 结构、feed 元数据、分页、auth) | 低——mock 的 JSON 可能与真实 Miniflux 响应漂移 |
| CI 代价 | 需要 docker-in-docker(CI runner 需 docker 守护进程) | 无,纯 pytest |
| 与其它 integration 一致性 | **不一致**(唯一 docker e2e) | 一致 |
| 维护成本 | docker-compose 定义 + 容器健康检查 + 服务起停管理 | httpserver mock 响应 |

**采纳理由**:feed 的核心价值就是对接 Miniflux,API 兼容性是关键风险点(miss 一个字段就导致整个 integration 失效)。mock 无法发现"真实 Miniflux 返回的 entry JSON 结构与假设不符"这类问题。真实容器是验证集成迁移功能正常的关键(spec 15 §1.2:e2e 测"契约 + 跨 integration 协同",对 feed 而言"契约"= 与 Miniflux 的真实契约)。

**记录此例外**:实现时必须在 e2e docker compose 文件和 conftest 顶部注释说明这是有意例外,指引未来维护者理解为何 feed e2e 与其它 integration 不同。

### 15.2 docker-compose 定义

参照 feeber e2e(`e2e/docker/docker-compose.yml`,已核实),起 **Miniflux + PostgreSQL** 两个容器(Markpost 用 progress 既有 httpserver mock 即可,无需真实容器,因为 markpost 不是 feed 的数据源):

```yaml
# e2e/feed/docker-compose.yml
services:
  miniflux:
    image: miniflux/miniflux:2.2.17          # 与 feeber e2e 对齐的版本
    healthcheck:
      test: ["CMD", "/usr/bin/miniflux", "-healthcheck", "auto"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    ports:
      - "18080:8080"
    depends_on:
      db:
        condition: service_healthy
    environment:
      - DATABASE_URL=postgres://miniflux:password@db/miniflux?sslmode=disable
      - RUN_MIGRATIONS=1
      - CREATE_ADMIN=1
      - ADMIN_USERNAME=admin
      - ADMIN_PASSWORD=password
    networks:
      - feed-e2e-network

  db:
    image: postgres:17-alpine
    environment:
      - POSTGRES_USER=miniflux
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=miniflux
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "miniflux"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - feed-e2e-network

networks:
  feed-e2e-network:
    driver: bridge
```

**版本/端口/凭据**(对齐 feeber e2e):

| 项 | 值 |
|---|---|
| Miniflux image | `miniflux/miniflux:2.2.17` |
| Miniflux host port | `18080` |
| Miniflux admin | `admin` / `password`(CREATE_ADMIN 自动创建) |
| PostgreSQL image | `postgres:17-alpine` |
| PostgreSQL creds | `miniflux` / `password` / db `miniflux` |

### 15.3 服务生命周期管理

`e2e/feed/conftest.py` 提供一个 session 级 fixture 管理 docker 生命周期(参照 feeber `e2e/docker.py`):

```python
@pytest.fixture(scope="session")
def miniflux_service():
    """起 Miniflux + PG docker,返回 (base_url, api_key)。session 级复用。"""
    # 1. docker compose up -d(幂等:已运行则跳过)
    # 2. 轮询 docker compose ps 直到 miniflux Health=healthy(超时 120s)
    # 3. miniflux.Client(base_url, username/password).create_api_key("e2e-test-key")
    # 4. yield (base_url="http://localhost:18080", api_key=token)
    # 5. teardown: docker compose down -v
```

**幂等起 + 销毁停**:`up` 前检查是否已运行(跳过);`down -v` 总是清 volume(参照 feeber)。

### 15.4 测试数据注入(经 Miniflux API)

参照 feeber `e2e/contrib/miniflux/data.py`(已核实),通过 Miniflux REST API 注入测试数据:

1. **OPML import** 创建 feed 壳(`client.import_feeds(opml)`),`xmlUrl` 指向不存在的 server(仅创建壳,不真实抓取)。
2. **`client.import_entry(feed_id, url, title, content, status="unread")`** 注入未读条目。
3. 每个 phase 开始 `clear_all_data`(删所有 feeds + 非 Uncategorized categories)。

helper 放 `e2e/feed/conftest.py`:`create_feed_with_entries(client, name, count, content_len=200)`。

### 15.5 e2e 测试矩阵(4 个 phase,对齐 feeber e2e 结构)

feed e2e 限定 **4 个 case**(对齐 feeber 4 phase;spec 15 每 integration 限 5 个 e2e 的约束内)。每个 case 用 `agent.override(model=TestModel())` 免真实 AI(AI 内容不 assert,只 assert 结构 + 契约)。

| 文件 (`e2e/feed/`) | 场景(对齐 feeber phase) | 断言焦点 |
|---|---|---|
| `test_first_run_single_feed.py` | 单 feed 2 条未读 → 首次 run | 聚合报告落库(report_type="feed", commit_count=2);FeedTracker 建 1 行(last_entry_id=最大 id,last_check_time 盖戳);报告含 1 feed 2 entries |
| `test_incremental_new_entries.py` | 同 feed 再加 3 条未读 → 第二次 run | 新报告 commit_count=3(只新条目);水位推进到新最大 id;旧 2 条不重复处理 |
| `test_multiple_feeds.py` | 3 feeds(3/2/2 条)→ run | commit_count=7;FeedTracker 建 3 行;报告含 3 feed sections;每个 feed 水位各自推进 |
| `test_checkpoint_and_gc.py` | run 后删 1 feed(Miniflux API)→ 再 run | 被删 feed 的 FeedTracker 行 GC;剩余 feed 不受影响;水位正确 |

**额外可选 case**(若需验证 markpost batch 切分,用 progress 既有 httpserver mock markpost,不起真实 markpost 容器):
- `test_report_batch_split.py`:`[core.markpost] max_batch_size=500` 强制切多 batch → 通知只发 1 次(total_batches>1),markpost_url 指第一段。

### 15.6 e2e 配置与 AI 免调

e2e fixture 把 Miniflux 连接写入 DB config 表(section="feed"),AI 走 `agent.override(model=TestModel())` + `[core.analysis]` 留空(AI 全降级,e2e 不 assert AI 内容,只 assert 结构/契约)。

`ALLOW_MODEL_REQUESTS=False`(根 conftest autouse)保证不意外调真实 AI。

### 15.7 e2e 执行

```bash
uv run pytest -m e2e e2e/feed/     # 仅 feed e2e(需 docker)
uv run pytest -m "e2e and not feed" # 排除 feed e2e(无需 docker,CI 快速跑)
```

**CI 集成**:feed e2e 需 docker-in-docker。CI 流水线应:默认跑 `-m "not e2e or (e2e and not feed)"`(免 docker 快速门禁),release 前或 nightly 跑全量含 feed e2e。具体 CI 编排由独立 CI 规范承担(待建),不在本 spec。
