# 09 · 报告生成

## 决策:流水线拆解 + Jinja2 autoescape + nh3 sanitize + 双落库简化

`cli/reports/` 是核心共享包(提供报告生成基础接口 + 扩展性),God 函数拆为流水线阶段,Jinja2 默认 autoescape,markdown 经 nh3 sanitize。**保留**原 batch 切分、AI 标题/摘要前置注入、oversize stub 机制。

## 归属:cli/reports/

报告生成链路(追踪后聚合 + AI 标题 + 发布 + 通知)**只 CLI 触发**,API 只读已落库 Report 行(审计证实 API 不 import reporting)。故进 `cli/reports/`。

## 落库矩阵(明确决策)

**简化决策**:repo integration 从原"聚合 + 每 repo 双落库"简化为**只落库 1 条聚合报告**。proposal/changelog/discovered 维持原行为(各落 1 条聚合报告)。

| integration | report_type | 落库条数 | commit_count 语义 |
|---|---|---|---|
| repo | `repo_update` | 1(聚合) | 全部 repo 的 commit 总数 |
| proposal | `proposal` | 1(聚合) | notifiable 报告数(`len(reports)`) |
| changelog | `changelog` | 1(聚合) | 新增版本总数(`sum(len(new_entries))`) |
| discovered | `repo_new` | 1(聚合) | 发现仓库数(`len(new_repos)`) |

### 简化理由(每 repo 落库取消)

- 原 `reporting.py:296-313` 为每个 repo 单独落库一条 `Report(repo_id=..., commit_hash=..., content=...)`。
- **简化后只落库聚合报告**——Web UI 已经通过 `GET /api/v1/reports?report_type=repo_update` 查询聚合报告,每 repo 单独报告在 UI 不单独展示。
- 删除每 repo 落库后,`Report.repo_id` 字段可保留(供未来扩展)但默认不再使用。

### proposal/changelog/discovered 的落库时机

这三个 integration 的报告**不通过 reports pipeline 落库**——它们在自己的通知函数里 `save_report` 后直接调 `publish_monolithic_report` + `send_notification`。

**新架构下**:这三个 integration 把聚合报告内容塞入 `ReportSection.payload`,reports pipeline 统一落库 + 发布 + 产 `ReportEvent` 到通知管道。这样所有 integration 的落库路径统一。

## God 函数拆解为流水线

原 `reporting.py:231-438` 的 `process_reports` 是 110 行 God 函数(7 职责),拆为流水线阶段:

```
cli/reports/pipeline.py:
  collect_outcome(outcome) -> ReportContext            # 状态统计 + 准备上下文
  render_sections(ctx) -> list[Section]                # 各 integration 报告段渲染(Jinja2)
  render_aggregated(sections, ...) -> str              # 聚合 Markdown(无 summary 前置)
  generate_title_summary(aggregated, ai) -> TitleSummary  # AI 标题/摘要(fallback 降级)
  inject_summary(aggregated, summary) -> str           # summary 前置注入(见下)
  persist(ctx, full_content, title_summary) -> ReportId  # 存 DB(事务)
  publish_batches(ctx, markpost) -> list[BatchUrl]     # 分批 + MarkPost 上传 + oversize stub(见下)
  run(ctx) -> ReportOutcome                            # 编排上述阶段
```

### `run()` 职责边界(强制)

**只编排**(按序调阶段 + 收集结果),**不含业务逻辑**。呼应 05 `cli/core.py` 的 `run()` 同理。

### 失败处理(结构化,不静默吞)

- 阶段返回 `ReportOutcome`(成功/失败/部分失败 + 收集错误),不再静默吞。
- `generate_title_summary` 失败 → fallback 默认标题(明确标记降级),**不阻断**流水线。

### AI 标题/摘要前置注入(恢复原行为)

**原 `reporting.py:264-281` 的行为**:AI 生成的 `unified_summary` 前置到聚合报告内容,给读者一个概述。

```
full_content = f"{summary.strip()}\n\n{aggregated_report}" if summary.strip() else aggregated_report
```

- `full_content` 落库为聚合 Report 的 content。
- 失败 fallback:title=`"Progress Report for Open Source Projects - {date}"`,summary=""(不前置)。
- **新 pipeline 必须保留此前置注入**,不能把 summary 单独存而不注入 content。

### Batch 切分与按 batch 派发通知(恢复原行为)

**原 `reporting.py:321-426` 的行为**:MarkPost 有单篇大小上限(`markpost.max_batch_size`),当报告总大小超限时,切成多个 batch 上传,每个 batch 派发一次通知。

**切分算法**:
- 有效上限 = `max_batch_size * 0.8`(BATCH_MARGIN,预留 20% 给 summary/template 开销)。
- 逐个 repo 的已渲染 section 累加,超限时切出新 batch。
- 单个 repo 超 effective_limit → 独立成一个 batch。

**每 batch 处理**:
1. 组装 batch body:sections + unified_summary(前置)+ status block + footer。
2. 检查大小:若超 `max_batch_size`,触发 oversize stub(见下)。
3. 上传到 MarkPost,得到独立 URL。
4. **派发一次通知**:携带 `batch_index`/`total_batches`/`batch_commit_count`/`batch_repo_statuses`(只含本 batch 的 repo)。通知 title 固定为 `_("Progress Report for Open Source Projects")`(**不是** AI 生成的 unified_title)。通知 summary 是 `_("This report covered {count} projects with {commits} commits total").format(...)`。

**title 的 batch 后缀**:所有通知 title 经 `add_batch_indicator`——`total_batches > 1` 时追加 ` ({batch_index+1}/{total_batches})`。

**Batch 行落库**:
- 若一个 Report 产出多个 MarkPost URL,每个 URL 落一条 `Batch` 行(`seq` 从 1,`title` 是**不带** `(n/m)` 后缀的干净 title);`Report.markpost_url` 置空。
- 若只 1 个 URL,直接写 `Report.markpost_url`,不落 Batch 行。

### Oversize stub 机制(恢复原行为)

两个场景:

**场景 A:单篇报告超限**(`publish_monolithic`,用于 proposal/changelog/discovered):
- body 字节大小 ≤ `max_batch_size` → 正常上传。
- 超限且 `web.base_url` 已配置 → 生成 stub:
  ```
  > ⚠️ This content is too large to publish here. [View the complete report in the WebUI]({url}).
  ```
  其中 url = `{web_base_url}/report/{report_id}`。上传 stub 替代 body。
- 超限但 `web.base_url` 未配置 → **跳过上传**,记 warning,返回空 URL。
- **数据库里存的是完整 body**(save_report 在 publish 之前,存未 stub 的完整内容);MarkPost 上是 stub。

**场景 B:批量报告中单个 repo 超 limit**(`publish_batches`):
- 组装 batch body 后检查大小。
- 超 limit 且 batch 只含 1 个 repo 且 `web.base_url` 已配置 → 用 stub 替代 batch body 重新组装。
- 超 limit 但不满足上述条件 → **跳过该 batch**,记错误。

**关键不变量**:
- stub 只影响 MarkPost 上传,**不影响数据库**——DB 始终存完整内容。
- 需要配置 `web.base_url` 才能用 stub。

### 修当前病根

| 病根 | 修复 |
|---|---|
| 聚合报告存失败 → 静默 `return` | 结构化 ReportOutcome,错误上抛 |
| 批次上传错误只 log | 收集到 errors |
| 默认标题字符串复制 3 处 | 收敛到一处常量 |
| `generate_report_title_and_content` 死代码 | 删除 |
| 分批 `2**63-1` 哨兵(reports 空会 IndexError) | 删,空列表早返回 |
| `process_reports` 改写共享 `content` 副作用 | 阶段间显式数据传递 |
| **新 pipeline 硬编码 `total_batches=1, batch_index=0`** | **恢复 batch 切分** |
| **新 pipeline 不注入 summary 到 content** | **恢复 summary 前置注入** |
| **新 pipeline 无 oversize stub** | **恢复 oversize stub** |

## Jinja2 autoescape(修 XSS 根因)

```python
# utils/templating.py
env = Environment(
    loader=FileSystemLoader(dirs),
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "xml", "j2"),
        default_for_string=True,  # 字符串模板也转义
    ),
)
```

### 决策理由(源码核实)

- 当前 `templates.py:64` `autoescape=False` 是 XSS 根因——HTML 通知模板插用户数据不转义。
- `select_autoescape` 是 Jinja2 文档化的安全默认(`jinja2/utils.py:581-634`)。
- markdown 渲染的 HTML 插入模板时用 `Markup`(`|safe`)**在 sanitize 之后**——绝不之前。
- 删手写 `escape_html` filter + 调用者记得转义的脆弱性。

## Markdown → HTML + nh3 sanitize(修存储型 XSS)

```python
# utils/markdown.py
import nh3
from markdown_it import MarkdownIt

md = MarkdownIt("commonmark", {"breaks": True, "html": True})


def render_markdown(text: str) -> str:
    raw_html = md.render(text)
    return nh3.clean(raw_html, ...)  # allowlist sanitize
```

### 决策理由(源码核实)

- **bleach 已废弃**(2026-06-05官宣,`bleach/README.rst`)。**nh3 是 bleach 官方继任者**(Rust/ammonia 绑定,v0.3.6,~20× bleach)。
- `markdown-it-py` `html=True` 无 sanitize = 存储型 XSS(审计证实 AI 生成内容含 commit message/release note,部分受上游影响)。`html=True` + nh3 = defense-in-depth,允许 AI 输出受控 HTML 子集 + nh3 allowlist 强制约束。
- nh3 默认 `link_rel="noopener noreferrer"`、`url_schemes` 控制——链接硬化。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| `html=False`(js-default preset,raw HTML 转义) | 失去 AI 输出合法 inline HTML 的能力;`html=True`+nh3 更灵活 |
| bleach | 官方废弃 |
| 手写 sanitize | 重复造轮子,易漏 |

## 模板组织

```
cli/reports/templates/reports/    # 报告聚合模板 + 共享 macro(report_base.j2)
integrations/*/templates/         # 各 integration 自带的报告段模板
```

### 模板归属与引用方向(重要)

- 报告聚合模板(`aggregated_report.j2`)在 `cli/reports/templates/reports/`。
- **共享 macro**(`report_base.j2` 的 `footer`/`status_icon`)在 `cli/reports/templates/reports/`——它们是跨 integration 共享的原语,属核心基础组件。
- 各 integration 的报告段模板在自己包内(`integrations/{name}/templates/`,自包含,呼应 06)。

**引用方向规则(强制)**:
- ✅ integration 模板可以引用核心基础组件:`{% from "report_base.j2" import footer, status_icon %}`。
- ❌ **核心代码不得反向引用** integration 专属模板——`cli/reports/` 不得 `{% include "integrations/repo/..." %}`,也不得在核心代码里硬编码 integration 的模板路径。
- 核心通过注册表动态发现 integration 的模板目录(见 06 的 `_collect_integration_template_dirs`),不静态引用。

### 渲染时的 payload 传递

`render_sections` 阶段渲染每个 integration 的报告段时:
```python
template.render(section=sec, result=result, integration_name=name, **sec.payload)
```
`sec.payload` 的字段被展开为模板变量——各 integration 在 `ReportSection.payload` 里塞自己模板需要的结构化字段(如 repo 的 `releases`/`commit_messages`,proposal 的 `grouped_events` 等)。

## feedgen(RSS,保留)

RSS 生成用 feedgen(探查证无更好替代)。但修正:RSS 内容必须经 nh3 sanitize 后的 markdown(当前 `rss.py` 喂未 sanitize 的 `render_markdown`)。

## 删除清单

| 删除 | 理由 |
|---|---|
| `reporting.py`(God 函数) | 拆为 pipeline |
| `publish.py` | 并入 pipeline 的 publish_batches |
| `autoescape=False` | 改 select_autoescape |
| 手写 `escape_html` filter | autoescape 替代 |
| `StorageType` enum + `report.storage` | 报告默认存 DB,markpost 可选叠加(见 02) |

## 与 02 的接口

- 报告**默认存 DB**(无条件)。
- 配了 markpost(`enabled=true` + `url`)→ **额外上传到 markpost**(非存储策略选择,见 02 删 storage 概念)。
