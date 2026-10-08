# changelog · 变更日志跟踪

> 本规范定义 changelog integration 的**完整业务行为**。读者对象:实现者、审查者、后续维护者。规范即验收标准——每一条"必须"都应对应可通过的测试。

## 1. 业务概述

changelog integration 周期性地从配置的远程 URL 拉取变更日志页面，解析出其中的版本条目，识别自上次检查以来**新增的版本**，为每个新增版本生成报告段、更新状态、产出通知事件。

**本 integration 不调用 AI**——版本条目的 `description` 字段已经是结构化的人类可读文本（从 changelog 页面直接提取），不需要 AI 再加工。

### 支持的日志页面格式

| 格式标识 | 业务含义 | 典型来源 |
|---|---|---|
| `markdown_heading` | Keep-a-Changelog 风格的 Markdown（二级标题 `## [x.y.z]`） | 多数 JS/Rust 项目 |
| `html_chinese_version` | HTML 页面中 `uTools vX.Y.Z` 形式的版本标记 | 某些国内项目（如 uTools） |

### 业务流程

1. **配置同步**(`sync`):把 config 中的 trackers 同步到状态表(upsert + GC)。
2. **逐个检查**(`run`):对每个 tracker 执行检查——拉取页面、解析版本、识别新增、更新水位、产出检查结果。
3. **生成报告与通知**:
   - 为每个有新增版本的 tracker 生成报告段(渲染**全部**新增版本)。
   - 报告段经 reports pipeline 聚合,落库为一条 `report_type="changelog"` 的聚合报告(commit_count = 新增版本总数)。
   - 同时构造**一个** `ChangelogEvent`(只携带最新的那个新增版本),经 notifications dispatcher 派发到通知通道。

### 关键业务规则

1. **首次运行只上报最新的 1 个版本**——不一次性刷屏,让用户先确认跟踪已生效。
2. **水位推进仅发生在检查成功且有新版本时**——失败、无新版本、被禁用都不推进水位。
3. **不依赖版本号语义比较**(不做 semver 排序)——完全依赖"日志页面中文档顺序 = 新到旧"的约定,通过在版本列表中**线性查找**水位的所在位置来确定哪些是新增的。
4. **水位失效时只上报最新的 1 个版本**——当日志被重写导致已记录的水位版本号在当前列表中找不到时,视为异常情况,保守地只上报最新 1 个并附带提示信息,避免刷屏(此情况罕见,对用户影响面很小)。
5. **通知事件每个 tracker 只发一个**(携带最新的新增版本),但**报告里渲染全部**新增版本——通知用于轻量提醒,报告用于完整记录。
6. **并发可配置**——`run` 接受 `concurrency` 参数(默认 1 串行)。本 integration 不调 AI,因此并发对拉取/解析阶段有正面收益。
7. **config 修改后状态表不立即同步**——`sync` 只在 `run` 流程开始时执行(详见 spec 06)。

---

## 2. 数据模型

### `ChangelogTracker`(表 `changelog_trackers`)

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `name` | CharField(255) | required | — | 人类可读名称,用于报告与通知展示 | — |
| `url` | CharField(255) | **unique** | — | changelog 页面 URL;**身份键**(upsert/GC/dedup 都基于它) | — |
| `parser_type` | CharField(255) | required | — | `"markdown_heading"` 或 `"html_chinese_version"` | — |
| `last_seen_version` | CharField(255) | nullable | None | 已上报的最新版本号(水位) | None:该 tracker 从未成功上报过版本(首次运行或历史检查全部失败) |
| `enabled` | BooleanField | — | True | 是否启用 | — |
| `proxy` | CharField(1024) | — | `""` | 该 tracker 拉取专用的 HTTP(S) 代理 URL;空 = 直连 | — |
| `last_check_time` | DatetimeField | nullable | None | 上次检查时间戳 | None:该 tracker 从未执行过检查(新建后尚未运行,或一直处于禁用状态) |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | `updated_at` 由 `BaseModel` 在每次 save 时自动刷新 | — |

### 字段语义精确说明

**`url` 是身份键**:
- config 中修改 `url` 等价于"删除旧 tracker(含其水位)+ 创建新 tracker"——水位不会随 URL 变更迁移。
- 修改 `name`/`parser_type`/`enabled`/`proxy` 触发 update(不重建,水位保留)。

**`last_seen_version`(水位)的推进规则**:
仅当检查返回 `success` **且**有新增版本时,水位推进到新增版本列表中的第一个(即最新的那个新增版本)。其他三种结果(`no_new_version`、`failed`、`skipped`)都**不**推进水位。

**`last_check_time`(检查时间戳)的盖戳规则**:
- `success`、`no_new_version`、`failed` 三种终态都盖戳为当前时间。
- `skipped`(禁用)**不**盖戳——因为禁用的 tracker 根本没执行检查动作,时间戳应保持"上次真正检查的时间"的语义。

---

## 3. 配置

### `ChangelogItemConfig`(单个 tracker 配置)

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `name` | str | 是 | — | 人类可读名称 |
| `url` | str | 是 | — | changelog 页面 URL |
| `parser_type` | `Literal["markdown_heading", "html_chinese_version"]` | 是 | — | 解析器类型 |
| `enabled` | bool | 否 | True | 是否启用 |
| `proxy` | str | 否 | `""` | 该 tracker 拉取专用的 HTTP(S) 代理 URL(如 `http://127.0.0.1:7890`);空(默认)则直连。必须是 `http://` 或 `https://` 开头,否则配置校验报错。与 `core.github.proxy` 相互独立 |

配置类 `extra="forbid"`:出现未定义字段时报错。TOML 中 `trackers` 接受 list 或以数字字符串为键的 dict(dict 会被按数字键排序后转成 list)。

### `ChangelogIntegrationConfig`(integration 顶层配置)

| 字段 | 类型 | 默认 |
|---|---|---|
| `trackers` | `list[ChangelogItemConfig]` | `[]` |

配置从 DB config 表(section = `"changelog"`)读取。读不到时回退全默认(空 trackers 列表)——这是 zero-config 行为。

---

## 4. 插件生命周期

### `setup`
接收共享依赖(CoreConfig 和共享的 aiohttp ClientSession)。从 DB 读取 `ChangelogIntegrationConfig`;解析失败时回退默认并记录 warning。

### `sync` —— 配置同步

把 config 中的 trackers 同步到 `ChangelogTracker` 表。业务规则:

1. 计算期望的 URL 集合(来自 config 的所有 tracker URL)。
2. 对每个 config tracker:
   - 若 DB 中不存在该 URL → 创建新行(水位和检查时间戳都初始化为 None),计入"新增"。
   - 若 DB 中已存在 → 比较 `name`/`parser_type`/`enabled`/`proxy`(**不**比较 url,它是查找键);任一变化则更新字段,计入"更新"。
3. **GC**:DB 中存在但不在期望 URL 集合中的行 → 删除,计入"删除"。GC 基于 URL 集合,与 `enabled` 无关——禁用的 tracker 只要还在 config 里就保留。

**sync 的触发时机**:只在 `run` 流程开始时执行(`core.py` 里 `setup → sync → run` 的固定顺序)。`PUT /api/v1/config/changelog` 成功后只写 DB config 表,**不**调用 sync。这是有意的设计——状态表是程序内部 checkpoint,不对用户暴露(详见 spec 06)。

### `run(*, concurrency: int = 1)` —— 执行检查

遍历 config 中的 trackers(按 config 顺序):

对每个 tracker:
1. 若该 tracker 不在 DB 中(config 有但 sync 没跑)→ 生成一个错误报告段(错误信息为 "Tracker missing from database; run sync() first"),状态标记为失败。**不自动 sync**。
2. 否则执行检查(详见 §5),产出 `ChangelogCheckResult`。
3. 若检查成功且有新增版本:
   - 为新增版本列表中的**每个**版本生成报告段(详见 §6)。
   - 同时构造**一个** `ChangelogEvent`(详见 §7)加入 `RunResult.events`。

**错误聚合**:
- 单个 tracker 的业务异常 → 计入 `RunResult.errors`,整体状态降为 `partial`。
- 其他意外异常 → 包装为业务异常后同上。
- 若有错误且无任何成功报告 → 整体状态降为 `failed`。

**并发**:支持通过 `concurrency` 参数调整并发度,默认 1(串行)。本 integration 不调 AI,并发对 HTTP 拉取阶段有正面收益。

### `teardown`
释放持有的引用。共享的 ClientSession 由上层 lifespan 管理,不在此关闭。

---

## 5. `check` 核心算法

### 5.1 检查结果的四种状态

| 状态 | 触发条件 | 水位推进 | 检查时间戳盖戳 |
|---|---|---|---|
| `skipped` | tracker 被禁用 | 否 | **否** |
| `success` | 解析成功 **且** 有新增版本 | 推进到新增版本列表的第一个(最新的) | 是 |
| `no_new_version` | 解析成功 **但** 无新增版本 | 否 | 是 |
| `failed` | 拉取失败 / 解析失败 / 任何异常 | 否 | 是 |

### 5.2 检查流程

1. **禁用检查**:若 tracker 被禁用,直接返回 `skipped` 结果,不更新任何字段。
2. **代理解析**:若 tracker 配置了 `proxy`(非空)→ 该 tracker 的拉取请求以 per-request `proxy=` 走该代理(详见 §9);为空 → 直连。
3. **拉取页面**:从 URL 拉取 changelog 内容(详见 §9)。拉取失败(HTTP 错误、网络错误、超时)→ 返回 `failed`,错误信息含异常详情。
4. **解析版本**:用与 `parser_type` 匹配的解析器解析内容(详见 §8)。解析失败(无版本头、HTML 无法解析、未知 parser_type)→ 返回 `failed`。
5. **空结果防御**:若解析返回空列表 → 返回 `failed`(错误信息 "No version entries found")。
6. **识别新增版本**:调用 `_detect_new_entries`(详见 §5.3),返回 `(新增版本列表, 警告信息)`。
7. **无新增版本**:盖戳检查时间戳,返回 `no_new_version`(携带最新版本号供日志展示)。
8. **有新增版本**:推进水位到新增版本列表的第一个(最新的),盖戳检查时间戳,返回 `success`(携带新增版本列表;若 `_detect_new_entries` 返回了警告信息,则塞进结果的 `error` 字段传递)。

### 5.3 `_detect_new_entries` —— 识别新增版本的核心业务逻辑

本函数决定"哪些版本是新的"。**完全不依赖版本号语义比较,不排序**,只依赖"列表中文档顺序 = 新到旧"的约定。

**业务决策树**(四个分支,按顺序判断):

| 分支 | 条件 | 业务行为 | 警告 |
|---|---|---|---|
| 1. 空列表 | 版本列表为空 | 返回空(防御性,正常路径不会到这里) | 无 |
| 2. 首次运行 | 水位为 None(从未上报过) | **只返回最新的 1 个版本**(列表第一个) | 无 |
| 3. 命中水位 | 在列表中找到了水位对应的版本 | 返回该版本**之前**的所有版本(即比水位更新的全部) | 无 |
| 4. 未命中水位 | 水位对应的版本不在当前列表(日志被重写等) | **只返回最新的 1 个版本**(列表第一个) | "Stored last_seen_version was not found in changelog; notified latest only" |

**关键不变量**:
- **不排序**——依赖解析器产出的列表已经是文档顺序(最新在前是常见约定)。
- 分支 3 的"该版本之前的全部"在"最新在前"约定下 = "所有比水位更新的版本"。
- 分支 4 的警告是**业务上有意义的信息**(告诉用户水位失效了),通过结果的 `error` 字段传递(**不**抛异常,不影响检查成功状态)。
- 分支 2 和分支 4 都"只返回 1 个",但语义不同:分支 2 是首次运行(正常),分支 4 是水位失效(异常,附带警告)。

---

## 6. 报告生成与落库

### 6.1 报告段(`ReportSection`)

每个检查成功的 tracker(有新增版本)映射为报告段。报告模板 `templates/changelog_report.j2` 必须渲染**全部**新增版本(与通知事件只携带最新的一个不同)。

报告段的 `ReportSection.payload` 塞入模板需要的结构化字段:
- `name`: tracker 名称
- `url`: tracker URL
- `new_entries`: `list[ChangelogVersion]`(每个含 `version` + `description`)

### 6.2 模板结构(`changelog_report.j2`)

- 每个 tracker 一个二级标题:`## [{tracker 名称}]({tracker URL})`
- 每个 新增版本:版本号小标签(🏷️)+ 描述正文
- tracker 之间用 `---` 分隔
- 结尾 `{{ footer(generation_time) }}`(footer macro 来自核心 `report_base.j2`)

### 6.3 聚合报告落库

报告段经 reports pipeline 聚合后,落库为一条 Report 行:

| 字段 | 值 |
|---|---|
| `report_type` | `"changelog"` |
| `commit_count` | 新增版本总数(`sum(len(new_entries) for each tracker)`) |
| `title` | 固定 `"Changelog Updates - {now:%Y-%m-%d %H:%M}"`(**不**经 AI 生成) |
| `content` | 渲染后的聚合报告内容 |

落库后经 MarkPost 发布(若配置),详见 spec 09。

---

## 7. 通知事件 `ChangelogEvent`

### 7.1 事件触发条件

仅当检查返回 `success` **且**有新增版本时,才为该 tracker 构造通知事件。`no_new_version`、`failed`、`skipped` 都不发事件。

### 7.2 事件内容

**每个 tracker 构造一个事件**(不是每个新增版本一个),使用**最新的那个新增版本**:

| 事件字段 | 取值 |
|---|---|
| `name` | tracker 名称 |
| `version` | 最新的新增版本的版本号 |
| `url` | tracker URL |
| `body` | 最新的新增版本的描述正文 |
| `kind` | 固定 `"changelog"` |

`ChangelogEvent` 定义在 `cli/notifications/events.py`。

### 7.3 通知 summary(固定拼接,**非** AI 生成)

changelog 通知的 summary 是固定拼接的字符串:
```
"{trackers 数} trackers updated, {总新增版本数} new versions: {name1} ({count1}), {name2} ({count2}), ... [, ... and {N} more]"
```
- 前 10 个 tracker 的明细,超过 10 个追加 `... and {N} more`。
- 此 summary 通过 `ReportEvent.summary` 承载(pipeline 聚合时构造)。

### 7.4 事件派发管道

事件加入 `RunResult.events`,经 `core.py` 的 `run_notifications` 统一派发到通知通道(详见 spec 10)。Dispatcher 路由到所有启用的通道。

### 7.5 通知模板

位于 `templates/notifications/changelog/{plain_text, html, card_json}.j2`,按通道内容类型渲染:

| 通道内容类型 | 渲染规则 |
|---|---|
| 纯文本(console) | 标题 + 空行 + 每事件的 `• {name_and_version} - {url}` 列表 + 空行 + markpost URL(若存在)。其中 `{name_and_version} = "{name} {version}".strip()` |
| HTML(email) | `<html><body><h2>{escaped title}</h2><ul><li><a href="{escaped url}">{escaped name} {escaped version}</a></li>...</ul>{可选 markpost 链接}</body></html>`,markpost 链接文本是 `_(View Detailed Report)` |
| 卡片 JSON(feishu) | 每事件一个 `div`(lark_md 格式 `• [{name} {version}]({url})`),事件间 `<hr>`,最后追加 `<hr>` + `_Generated by Progress_` div。`card_link` = markpost URL |

**title 的 batch 后缀**:`total_batches > 1` 时追加 ` ({batch_index+1}/{total_batches})`(详见 spec 09)。changelog 通常单 batch,该后缀多数情况不出现。

---

## 8. 解析器

### 8.1 版本条目数据结构

每个解析出的版本条目只包含两个字段:

| 字段 | 业务含义 |
|---|---|
| `version` | 规范化后的版本号字符串 |
| `description` | 该版本的描述正文(标题之间的全部内容) |

**没有**日期、body 等其他元数据字段。

### 8.2 解析器分发

| `parser_type` | 调用的解析器 |
|---|---|
| `"markdown_heading"` | Markdown 二级标题解析器 |
| `"html_chinese_version"` | uTools HTML 解析器 |
| 其他 | 抛 `ValueError("Unknown parser_type: ...")`(在检查中被捕获 → `failed`) |

### 8.3 Markdown 二级标题解析器(Keep-a-Changelog)

**业务目标**:从 Keep-a-Changelog 风格的 Markdown 中提取 `## [x.y.z]` 形式的版本标题及其描述。

**识别规则**:匹配以 `## `(两个井号 + 空格)开头的行,捕获标题文本。一级标题(`# `)不匹配。

**版本号提取步骤**(从标题文本中提取版本号,步骤顺序敏感):

1. **去括号**:若标题以 `[` 开头且含 `]`,取首个 `[` 到首个 `]` 的内容。例如 `[1.0.0]` → `1.0.0`。
2. **去 v 前缀**:若剩余文本以 `v` 或 `V` 开头且紧跟数字,去掉这个前缀。例如 `v1.2.3` → `1.2.3`。
3. **去日期后缀**:按空格、ASCII 连字符 `-`、en-dash `–`(U+2013)、em-dash `—`(U+2014)切分,取第一段。例如 `1.2.3 - 2024-01-01` → `1.2.3`。
4. **空值检查**:若结果为空,抛解析异常。

**已知边界行为**(业务上接受,不修复):

| 输入标题 | 提取结果 | 说明 |
|---|---|---|
| `2.0.0` | `2.0.0` | 标准情况 |
| `[v1.2.3] - 2026-01-01` | `1.2.3` | 三步全应用 |
| `v1.2.2` | `1.2.2` | 仅去 v |
| `[Unreleased]` | `Unreleased` | 成为"版本号"(业务上视为一个特殊版本) |
| `1.0.0-alpha` | `1.0.0` | prerelease 后缀被步骤 3 切掉(maxsplit=1) |
| `# 标题`(一级标题) | 不匹配 | 只匹配 `## ` |
| `[1.0.0](https://...)` | 畸形结果 `1.0.0](https://...)` | 内联链接格式,已知局限 |

### 8.4 uTools HTML 解析器

**业务目标**:从 HTML 页面中提取 `uTools vX.Y.Z` 形式的版本标记及其描述。类名叫 "Chinese" 是历史命名,实际匹配的是英文 `uTools`。

**识别规则**:正则匹配字面 `uTools` + 可选空白 + `v` + 版本号。版本号格式要求至少有一个点组(`7.5`、`7.5.1`、`7.5.1.2` 合法;纯 `7` 不匹配)。匹配大小写不敏感。

**解析步骤**:
1. 用 `lxml.html` 解析 HTML(**不**用 stdlib html.parser)。
2. 提取全部文本内容(剥除所有标签)。
3. 规范化文本(去多余空行)。
4. 用正则找出所有版本匹配。
5. 无匹配 → 抛解析异常。
6. 每个匹配的版本号取捕获组(不含 `v` 前缀);描述取该匹配结束位置到下一个匹配开始位置之间的文本。

---

## 9. HTTP 拉取

### 业务目标

从配置的 URL 拉取 changelog 内容,正确解码字节流为文本(包括处理被错误标注字符集的情况),对 HTTP 错误和网络错误给出明确的业务异常。

### 行为规范

- **复用** setup 接收的共享 ClientSession(**不**自行创建新的)。
- **超时**:总超时 30 秒,硬编码,不可 per-tracker 配置。
- **User-Agent**:字面值 `"progress"`(无版本后缀)。
- **HTTP 错误处理**:任何 4xx/5xx 响应都视为业务异常(拉取失败)。
- **网络错误处理**:`aiohttp.ClientError`(含连接错误、响应错误等)包装为业务异常。
- **超时处理**:`asyncio.TimeoutError` **不**被拉取逻辑内部捕获,会冒泡到检查逻辑的异常处理 → 检查结果为 `failed`。这是预期行为。
- **重试**:**无**——单次拉取,失败即检查失败。
- **代理**:per-tracker 自带代理 URL(`proxy` 字段)。非空 → 该 tracker 的拉取请求以 per-request `proxy=` 参数走此代理;空(默认)→ 直连。与 `core.github.proxy`(GitHub/git/v2ex 用的全局代理)相互独立,互不影响。配置校验要求非空值以 `http://` 或 `https://` 开头(配置写入时报错,而非运行期才失败)。共享 ClientSession 以 `trust_env=False` 创建,**不**读取 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量。

### 字符集解码(技术细节)

**业务目标**:正确解码响应字节流,特别是处理"HTTP header 标注的字符集与实际内容不符"的情况——最典型的场景是 UTF-8 编码的中文内容被错误标注为 `iso-8859-1`。

**解码策略**(按优先级尝试):
1. 若 HTTP header 提供了 charset,作为第一候选。
2. 始终将 UTF-8 作为最后兜底候选。
3. 按候选顺序尝试解码:解码失败 → 跳过;**mojibake 检测**(当前候选是 `iso-8859-1`/`latin-1`/`windows-1252` 之一,且解码文本含特征乱码字节序列)→ 跳过;否则采用。
4. 所有候选都失败 → UTF-8 + 替换字符兜底。

**关键**:不使用 `chardet`/`charset-normalizer`——完全依赖 HTTP header + mojibake 启发式 + UTF-8 兜底。

---

## 10. 边界行为与 edge cases

| 场景 | 期望行为 |
|---|---|
| 首次运行(水位为 None) | 只上报最新的 1 个版本,水位推进到它 |
| 无新版本(水位仍在列表首位) | 返回 `no_new_version`,不推进水位 |
| 水位对应的版本不在当前列表(日志被重写) | 只上报最新的 1 个版本 + 警告信息塞进 `error` 字段 |
| HTTP 404 / 500 | 拉取异常 → `failed` |
| HTTP 超时 | 超时异常冒泡 → `failed` |
| 网络错误(ClientError) | 包装为业务异常 → `failed` |
| `proxy` 值不是 `http://`/`https://` URL | 配置校验报错(PUT 被拒 / 加载时回退默认并告警),不会到运行期 |
| 空 changelog(无任何版本头) | 解析异常 → `failed` |
| 解析后版本列表为空 | 防御性异常 → `failed` |
| 禁用 tracker | 返回 `skipped`,不盖戳检查时间戳 |
| tracker 不在 DB(config 有但 sync 没跑) | 错误报告段,状态失败 |
| 未知 parser_type | `ValueError` → `failed` |
| parser_type 与内容不匹配 | 解析异常 → `failed` |
| Markdown 一级标题 | 不匹配 |
| Markdown `[Unreleased]` | 成为版本号 |
| Markdown 内联链接标题 | 畸形版本号(已知局限) |
| Markdown prerelease | 截断(已知局限) |
| HTML 非 uTools 内容 | 解析异常 → `failed` |
| 多个新版本一次检查 | 全部返回,水位推进到列表第一个 |
| charset 错误标注 | mojibake 检测 → 回退正确编码 |
| 单 tracker 失败 | 不影响其他 tracker |
| 超大 changelog | 无显式截断 |

---

## 11. 并发、超时、重试

| 项 | 值 |
|---|---|
| 检查并发模型 | `run(concurrency=...)`,默认 1(串行) |
| 单 tracker 拉取超时 | 总超时 30 秒(硬编码) |
| 拉取重试 | **无** |
| 单 tracker 失败对其他 tracker 的影响 | **无** |
| AI 调用 | **本 integration 不调 AI** |

---

## 12. 测试矩阵(验收清单)

### 数据模型与 sync
- [ ] `ChangelogTracker` 全字段建模,migration 与 model 一致
- [ ] 所有 nullable 字段的 None 语义正确
- [ ] `sync` 创建新 tracker(水位和检查时间戳都初始化为 None)
- [ ] `sync` 更新已存在 tracker 的 `name`/`parser_type`/`enabled`
- [ ] `sync` GC 不在 config 的 tracker(基于 URL 集合,与 enabled 无关)
- [ ] `sync` 修改 URL 等价于 delete+create(水位不保留)
- [ ] `sync` 只在 run 时触发,PUT /config 不触发

### check 与 _detect_new_entries
- [ ] 禁用 tracker → `skipped`,检查时间戳不改
- [ ] 首次运行 → 只返回最新的 1 个,水位推进到它
- [ ] 命中水位 → 返回它之前的全部,水位推进到列表第一个
- [ ] 未命中水位 → 只返回最新的 1 个 + 警告在 error 字段
- [ ] 无新版本 → `no_new_version`,不推进水位
- [ ] 拉取失败 → `failed`
- [ ] 解析失败 → `failed`
- [ ] 检查时间戳在 success/no_new_version/failed 盖戳,skipped 不盖戳

### 解析器
- [ ] markdown:`## 2.0.0` / `[v1.2.3] - date` / `v1.2.2` / `[Unreleased]` / 一级标题不匹配 / 无版本头抛异常
- [ ] markdown 版本号提取三步顺序
- [ ] html:`uTools v7.5.1` / 多版本 / 无匹配抛异常 / 非 uTools 内容抛异常
- [ ] 解析器分发:两种合法类型 + 未知类型抛 ValueError

### 拉取与字符集解码
- [ ] 复用共享 ClientSession
- [ ] User-Agent="progress"、总超时 30 秒
- [ ] 4xx/5xx 抛异常
- [ ] ClientError 包装为业务异常
- [ ] 字符集解码:UTF-8 / iso-8859-1+mojibake 跳过 / GBK / 无 header / 全失败 fallback

### run 与报告/通知
- [ ] 按 config 顺序遍历,单 tracker 失败不中断
- [ ] tracker 不在 DB → 失败 + 特定错误信息
- [ ] success+有新增版本时为每个新增版本生成报告段
- [ ] 报告模板渲染**全部**新增版本
- [ ] 聚合报告落库(report_type="changelog", commit_count=新增版本总数)
- [ ] title 是固定拼接(非 AI 生成)
- [ ] summary 是固定拼接(非 AI 生成)
- [ ] success+有新增版本时构造**一个** ChangelogEvent(携带最新的新增版本)
- [ ] no_new_version/failed/skipped 不发事件
- [ ] 3 个通知模板(纯文本/HTML/卡片 JSON)可达且渲染正确
- [ ] 错误聚合:单失败 → partial;全失败 → failed
- [ ] 并发参数可调(默认 1)
