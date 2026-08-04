# proposal · 标准提案跟踪

> 本规范定义 proposal integration 的**完整业务行为**。读者对象:实现者、审查者、后续维护者。规范即验收标准——每一条"必须"都应对应可通过的测试。

## 1. 业务概述

proposal integration 跟踪 5 类标准化提案仓库(EIP/ERC/PEP/RFC/DEP)中的提案文件变更。对每个启用的提案类型,clone 对应的 GitHub 仓库,基于 git commit checkpoint 计算**增量**文件变更,解析每个变更的提案文件以提取标题/状态/作者等元数据,检测提案的状态变化、文件移动、文件删除等事件,按事件类型调用 AI 生成分析,产出报告并派发通知。

### 支持的提案类型

| 类型 | 上游仓库 | 分支 | 提案目录 | 文件模式 |
|---|---|---|---|---|
| EIP | `https://github.com/ethereum/EIPs` | `master` | `EIPS` | `eip-*.md` |
| ERC | `https://github.com/ethereum/ercs` | `master` | `ERCS` | `erc-*.md` |
| PEP | `https://github.com/python/peps` | `main` | (root) | `pep-*.rst` |
| RFC | `https://github.com/rust-lang/rfcs` | `master` | `text` | `*.md` |
| DEP | `https://github.com/django/deps` | `main` | (root) | `*.rst`, `*.md` |

> ERC 使用独立仓库 `ethereum/ercs`,**不是** EIPs 仓库的子目录。ERC 的分支是 `master`(不是 main)——这是上游仓库的实际默认分支。

> 这 5 种类型的仓库/分支/目录/模式配置是**硬编码常量**,不从 config 文件读。config 只控制"启用哪些类型"。这是合理的工程权衡:每种类型的文件解析器各不相同(EIP 用 YAML frontmatter,PEP 用 RST field-list,RFC 用 markdown 等),新增类型必然需要新增解析器代码,因此"新增类型必须改代码"不可避免,硬编码反而让代码更清晰。

### 业务流程

1. **配置同步**(`sync`):把 config 中启用的类型同步到 `ProposalTrackerState` 表(upsert + GC)。
2. **逐类型检查**(`run`):对每个启用的类型执行检查——clone/fetch(含自愈)、首次或增量检查、文件解析、状态变化检测、AI 分析、产出报告。
3. **快照更新与通知过滤**:
   - tracker 对每个可解析的变更都更新 Proposal 表快照(无条件)。
   - tracker 对每个可解析的变更都产出 `ProposalReport`(不过滤)。
   - 业务层用 `should_notify` 规则过滤出值得通知的子集(notifiable)。
   - notifiable 报告聚合成一条 `report_type="proposal"` 的报告落库 + 派发 ProposalEvent 通知。

### 关键业务规则

1. **基于 git commit 的增量跟踪**——不是基于提案编号的全量比较。checkpoint 是 commit hash,不是 number。
2. **首次运行只产 1 个报告**(最新创建的提案),但**全部提案都入库**。**这是刻意的设计**:首次运行的目的是通知用户"配置跟踪已生效,后续将继续收到解析报告";历史提案数据刻意不解析(避免首次运行的 AI 成本爆炸和通知刷屏)。已入库的提案元数据供 Web UI 查询,但不会为历史提案生成分析报告。
3. **6 种事件分类**驱动 AI 分析模板选择(new/accepted/rejected/withdrawn/status_change/content_modified)。
4. **文件移动检测基于提案编号**——不基于 git rename detection。一个 delete + 一个 add 如果编号相同,识别为一次移动(只处理 add,跳过 delete)。
5. **删除处理区分终态/非终态**——非终态提案被删 → 标记为 WITHDRAWN;终态提案被删 → 状态不变。
6. **Rust RFC 标题特殊解析**——RFC 文件没有结构化标题,从 `RFC PR: ...#NNN` 提取 PR 号,调 GitHub API 拉 PR 标题作为 RFC 标题;任何失败都降级到 fallback(humanized Feature Name 或文件名),永不阻塞。
7. **clone 自愈**——corrupt HEAD(`.invalid` 占位符)通过 fetch+reset 失败检测,触发 rmtree + re-clone。
8. **AI 失败永不阻塞**——任何 AI 异常都降级为空 summary/detail,提案仍被跟踪和上报。
9. **快照更新与通知过滤分离**——详见 §11。
10. **并发可配置**——`run` 接受 `concurrency` 参数(默认 1 串行)。**注意**:AI 调用受全局信号量约束(`AI_CONCURRENCY=1`,见 spec 08),并发主要对 git/HTTP 工作生效。
11. **config 修改后状态表不立即同步**——`sync` 只在 `run` 流程开始时执行(详见 spec 06)。

---

## 2. 数据模型

### `ProposalTrackerState`(表 `proposal_tracker_states`)

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `kind` | CharField(255) | **unique** | — | `"eip"`/`"erc"`/`"pep"`/`"rfc"`/`"dep"` | — |
| `last_seen_commit` | CharField(255) | nullable | None | git commit checkpoint | None:该类型从未成功完成过检查(首次运行) |
| `last_check_time` | DatetimeField | nullable | None | 上次检查时间戳 | None:该类型从未执行过检查 |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | — | — |

> `last_seen_commit` 是 **commit hash**(不是提案编号)——增量检测基于 git diff。

### `Proposal`(表 `proposals`)

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `tracker` | ForeignKeyField→ProposalTrackerState | required | — | `related_name="proposals"`, `on_delete=CASCADE` | — |
| `number` | CharField(255) | required | — | 数字字符串如 `"1"`(不是 int) | — |
| `title` | CharField(255) | nullable | — | 提案标题 | None:该提案无标题(典型场景:Moved stub 文件,frontmatter 里没有 title 键) |
| `raw_status` | CharField(255) | — | `""` | 原始状态文本("Draft"/"Last Call"/...) | 空字符串:提案无状态字段(RFC)或解析时未提取到 |
| `status` | CharField(255) | required | — | 规范化后的 enum 值("draft"/"final"/...) | — |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | — | — |

**唯一约束**:`unique_together = (("tracker_id", "number"),)`——同一 tracker 内 number 唯一。

**CASCADE 语义**:当 `ProposalTrackerState` 行被删除(类型从 config 移除),其所有 `Proposal` 行自动级联删除——不会留下孤儿提案数据。

### 字段语义精确说明

**`raw_status` 与 `status` 的关系**:

| 字段 | 来源 | 业务含义 |
|---|---|---|
| `raw_status` | 解析器从提案文件直接提取的原始字符串 | 审计与 AI prompt 上下文(展示给 AI 看的精确状态文本,如 "Last Call") |
| `status` | 对 raw_status 应用 `normalize` 规范化后的 enum | 业务逻辑判断(通知过滤、模板选择、终态判断),如 "review" |

两者**总是成对更新**,基于同一次解析,在同一次落库中提交。不存在只更新一个的情况。双字段设计合理:raw_status 保留原始信息供 AI 和审计,status 支持高效的业务逻辑判断和查询。

---

## 3. 配置

### `ProposalIntegrationConfig`

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `trackers` | `list[str]` | `[]` | 启用的类型字符串列表,如 `["eip", "erc", "rfc"]` |

校验规则:
- **去重**:同一类型出现多次只算一次(TOML 无 set 类型,用 list 模拟 set 语义)。
- **拒绝未知类型**:不在 `{"eip", "erc", "pep", "rfc", "dep"}` 中的字符串报错。
- `extra="forbid"`。

配置从 DB config 表(section=`"proposal"`)读取,读不到时回退全默认(空 trackers——不跟踪任何类型)。

### 类型配置(硬编码)

5 种类型的仓库/分支/目录/模式配置是硬编码常量(见 §1 表格),不从 config 文件读。

---

## 4. 插件生命周期

### `setup`
接收共享依赖(CoreConfig 和共享的 aiohttp ClientSession)。从 DB 读取 `ProposalIntegrationConfig`,失败回退默认。

仅当 `cfg.github.gh_token` 非空时构造 GitHub API 客户端(用于 RFC PR 标题解析);token 为空则客户端为 None。无 token 时 RFC 仍被跟踪,但标题用 fallback(不调 GitHub API)。

### `sync` —— 配置同步

把 config 中启用的类型同步到 `ProposalTrackerState` 表:

1. 计算期望的类型集合(来自 config)。
2. 对每个期望类型:
   - 若 DB 中不存在 → 创建新行(`last_seen_commit` 和 `last_check_time` 都初始化为 None),计入"新增"。
   - 若 DB 中已存在 → 无字段可更新(除 kind 外都是 checkpoint),不操作。
3. **GC**:DB 中存在但不在期望集合中的行 → 删除,计入"删除"。**CASCADE 自动删除关联的 `Proposal` 行**——不会留下孤儿提案数据。

**sync 的触发时机**:只在 `run` 流程开始时执行。`PUT /api/v1/config/proposal` 成功后只写 DB config 表,**不**调用 sync(详见 spec 06)。

### `run(*, concurrency: int = 1)` —— 执行检查

遍历 config 中的类型:

对每个类型:
1. 执行检查(详见 §5),产出 `list[ProposalReport]`(内存中间结构,tracker 对每个可解析的变更都产出,不过滤)。
2. **业务层用 `should_notify` 过滤**(详见 §11)——从全部报告中筛出"值得通知"的子集。
3. 把过滤后的报告按类型分组、按编号排序,聚合成一条报告落库(`report_type="proposal"`)。
4. 构造 `ProposalEvent`(详见 §15)加入 `RunResult.events`。

**错误聚合**:
- 单个类型的业务异常 → 计入 `RunResult.errors`,整体状态降为 `partial`。
- 其他意外异常 → 包装为业务异常后同上。
- 若有错误且无任何成功报告 → 整体状态降为 `failed`。

**并发模型**:
- 支持通过 `concurrency` 参数调整并发度,默认 1(串行)。
- 并发度大于 1 时用信号量限制同时检查的类型数。
- 单类型异常被吞掉(记 warning),不影响其他类型。
- **AI 调用的全局序列化**:AI 请求受全局信号量约束(`AI_CONCURRENCY=1`),并发主要对 git/HTTP 工作生效。

### `teardown`
释放引用。

---

## 5. `check` 核心算法

### 5.1 检查流程

1. 读取该类型的硬编码配置(仓库、分支、目录、文件模式)。
2. 获取或创建 tracker 状态行。
3. 获取该类型的解析器(详见 §9)。
4. **clone 或更新仓库**(含自愈,详见 §5.2);clone 失败 → 上报错误(stage="clone")后重抛。
5. 读取当前 HEAD commit。
6. **首次运行**(checkpoint 为 None)→ 执行首次检查(详见 §6)。
7. **无新提交**(HEAD 与 checkpoint 相同)→ 盖戳检查时间戳,返回空。
8. **增量检查**:
   - 计算自 checkpoint 以来的变更文件列表(`git diff --name-status old..new`)。
   - 按目录和文件模式过滤(详见 §5.3)。
   - 识别移动的提案(基于编号,详见 §5.4)。
   - **Pass 1**:对每个变更/新增文件(status 不以 `D` 开头)执行 `_handle_changed`(详见 §7)。
   - **Pass 2**:对每个删除文件(status 以 `D` 开头),若编号不在"已移动"集合中则执行 `_handle_deleted`(详见 §8)。
9. 推进 checkpoint 到当前 HEAD;盖戳检查时间戳。
10. 返回全部报告(不过滤)。

**关键**:Pass 1 在 Pass 2 之前——重命名(同编号的 delete+add)在 Pass 1 已处理 add,Pass 2 的 delete 被"已移动"集合跳过。

### 5.2 clone 或更新(含自愈)

**业务目标**:保持本地提案仓库的克隆与上游同步,且能从 corrupt HEAD 状态自动恢复。

**算法**:
1. 从仓库 URL 派生本地存储路径(`state_home/proposal_repos/{sanitized_slug}`)。
2. 若本地已存在且含 `.git` 目录:
   - 尝试 fetch + reset 到配置分支,然后立即读取 HEAD 验证可用性。
   - 验证通过 → 复用本地克隆。
   - 验证失败(corrupt HEAD)→ 记 warning,删除本地目录,重新 clone。
3. 若本地不存在或已被删除 → 执行 clone:
   - 用 `git` 子进程(`git clone --single-branch --branch <branch> <url> <dest>`)。
   - `--single-branch` + 显式分支——避免拉取全部分支,减少时间和空间。
   - 超时为 git 操作超时的 2 倍(完整历史 clone 允许更长)。
   - 失败 → 抛业务异常。

**corrupt HEAD 自愈原理**:当 Git 的 HEAD 引用损坏时(表现为 `refs/heads/.invalid` 占位符),读取 HEAD commit 会抛 `ValueError`——这是触发 re-clone 的信号。

### 5.3 文件过滤

按目录前缀和文件模式过滤变更文件列表:
- 若该类型配置了提案目录(如 EIP 的 `EIPS`)→ 只保留以该目录为前缀的路径。
- 若未配置目录(如 PEP/DEP 的 root)→ 不限目录,全仓库匹配。
- 在文件 basename 上用 fnmatch 匹配文件模式。

### 5.4 移动检测(基于提案编号)

**业务目标**:识别"文件被移动/重命名"的情况,避免将其误判为"删除+新增"两个独立事件。

**算法**(不基于 git rename detection,完全基于提案编号):
1. 收集所有 add/modify 文件路径和所有 delete 文件路径。
2. 若 add 或 delete 列表为空 → 无移动。
3. 计算 add 文件中提取出的提案编号集合。
4. 对每个 delete 文件:若其编号出现在 add 集合中 → 标记为"已移动"。

**业务语义**:一个 delete 是"移动"当且仅当同编号的 add 出现在本次变更中。这种情况下 delete 会被跳过(已在 Pass 1 作为 add 处理)。

---

## 6. 首次检查

### 业务目标

首次运行时扫描提案目录的全部匹配文件,**全部入库**(建立提案元数据基线),但**只返回 1 个报告**(最新创建的提案)。

**这是刻意的设计**:首次运行的目的是通知用户"配置跟踪已生效,后续将继续收到解析报告"。历史提案数据刻意不解析(避免首次运行的 AI 成本爆炸和通知刷屏)。已入库的提案元数据供 Web UI 查询,但不会为历史提案生成分析报告。

### 算法

1. 确定提案目录(配置了目录则用 `repo_path/dir`,否则用 `repo_path`)。
2. 目录不存在 → 盖戳 checkpoint,返回空。
3. 递归扫描目录下所有匹配文件模式的文件。
4. 无匹配 → 盖戳 checkpoint,返回空。
5. 对每个匹配文件:
   - 解析文件(详见 §9);解析失败 → 记 debug 日志,跳过该文件。
   - 规范化状态。
   - **upsert 到 Proposal 表**(全部入库,建立基线)。
   - 读取该文件的创建时间(`git log --diff-filter=A`)。
   - 跟踪创建时间最新的文件。
6. 若无任何可解析文件 → 盖戳 checkpoint,返回空。
7. 重新解析最新文件;解析失败 → 盖戳 checkpoint,返回空。
8. 对最新文件:执行 RFC 标题解析(详见 §12)→ 再次 upsert(用解析后的标题)→ AI 分析(用 `proposal_new_prompt.j2` 模板,提案全文嵌入 prompt)。
9. 构造 1 个 `ProposalReport`(old_status=None)。
10. 盖戳 checkpoint,返回 `[该报告]`。

**关键不变量**:
- 首次运行**只返回 1 个报告**(最新创建的提案),即使全部提案都入库。
- RFC 标题解析在首次运行**也**执行(与增量一致)。
- 全部可解析的提案都 upsert 到 DB(首次 populate)。
- 空分析结果转为 None(`summary or None`)。

---

## 7. 变更/新增处理(`_handle_changed`)

对每个变更/新增文件(status 不以 `D` 开头):

1. 解析文件;解析失败 → 记 warning,返回 None(不影响其他文件)。
2. 执行 RFC 标题解析(详见 §12)。
3. 规范化新状态。
4. 查询 Proposal 表中该编号的现有记录;确定 old_status(无现有记录则为 None)。
5. 根据状态变化选择 AI 分析模板(详见 §10.6)。
6. **分支**:
   - **内容修改**(old_status 等于 new_status 且有现有记录):用 `git diff old..new -- <file>` 作为 AI 输入(嵌入 prompt);模板为 `proposal_content_modified_prompt.j2`。
   - **状态变化或新增**:用提案全文作为 AI 输入(嵌入 prompt);模板由状态变化决定。
7. **upsert 到 Proposal 表**(更新 title/raw_status/status 三个字段)。
8. 构造 `ProposalReport`(含 old_status/new_status/分析结果)。
9. **总是返回报告**——无论状态是否变化、是否值得通知,只要文件可解析就产报告。通知过滤是业务层的职责(§11)。

---

## 8. 删除处理(`_handle_deleted`)

对每个删除文件(status 以 `D` 开头,且编号不在"已移动"集合中):

1. 从文件名提取编号;提取失败 → 返回 None。
2. 查询 Proposal 表中该编号的现有记录;不存在 → 记 debug 日志,返回 None(忽略未知编号的删除)。
3. 读取 old_status。
4. **分支**:
   - **非终态**(old_status 不在终态集合中)→ 更新 status 为 WITHDRAWN,save;new_status=WITHDRAWN。
   - **终态**(old_status 在终态集合中)→ 状态不变;new_status=old_status。
5. 构造 file_url(用**前一次**的 checkpoint,因为新 commit 里文件已不存在)。
6. 构造 `ProposalReport`(title=现有记录的 title;**analysis_summary=None, analysis_detail=None**——删除不做 AI 分析)。

**关键**:
- 删除**不做 AI 分析**。
- 非终态提案被删 → 标记 WITHDRAWN(Draft/Review/Accepted/Stagnant/Deferred)。
- 终态提案被删 → 状态不变(Final/Active/Withdrawn/Rejected/Superseded/Moved/Unknown)。
- 未知编号的删除 → 忽略。

---

## 9. 解析器

### 9.1 解析结果数据结构

每个解析出的提案包含:

| 字段 | 业务含义 |
|---|---|
| `number` | 数字字符串,如 `"1"` |
| `title` | 提案标题,None 表示无标题(如 Moved stub) |
| `raw_status` | 原始状态文本,RFC 永远是空字符串 |
| `file_path` | 文件路径 |
| `full_text` | 文件全文(供 AI 分析) |
| `extra` | 额外元数据(category/type/pr_number/fallback_title 等) |

### 9.2 四种解析器

| 类型 | 解析器 | 文件格式 | 标题来源 | 状态来源 |
|---|---|---|---|---|
| EIP/ERC | EIP 解析器(共用) | Markdown + YAML frontmatter | frontmatter 的 `title` 键 | frontmatter 的 `status` 键 |
| PEP | PEP 解析器 | RST + field-list | RST field-list 的 `Title` | RST field-list 的 `Status` |
| RFC | RFC 解析器 | Markdown(无 frontmatter) | Feature Name humanize 或 GitHub PR 标题(详见 §12) | 无(永远为空,规范化为 ACCEPTED) |
| DEP | DEP 解析器 | 自动检测 YAML 或 RST | frontmatter/field-list 的 title 或 `DEP N: title` 标题行 | frontmatter/field-list 的 status |

### 9.3 EIP/ERC 解析器

**业务目标**:从 EIP/ERC 提案的 Markdown 文件中解析 YAML frontmatter,提取编号、标题、状态、类别、类型。

**编号提取**:
- 优先从 frontmatter 的 `eip` 键提取(ERC 文件也用 `eip` 键——历史原因);转为整数去前导零(如 `"007"` → `"7"`)。
- frontmatter 无 `eip` 键 → 从文件名提取(正则匹配 `eip-` 或 `erc-` 前缀 + 数字)。

**标题**:frontmatter 的 `title` 键;空字符串转为 None。

**状态**:frontmatter 的 `status` 键;缺失则空字符串。

**额外元数据**:`category`、`type`(非空时保留)。

### 9.4 PEP 解析器

**业务目标**:从 PEP 提案的 RST 文件中解析 field-list,提取编号、标题、状态、topic。

**编号提取**:
- 优先从 field-list 的 `PEP` 键提取;从中匹配数字。
- **`PEP` 键值无法匹配到数字**(如 `"TBD"`)→ **抛解析异常**(这是唯一对坏 header 抛异常的解析器)。
- field-list 无 `PEP` 键 → 从文件名提取(正则匹配 `pep-` 前缀 + 数字)。

**标题**:field-list 的 `Title` 键;空转为 None。

**状态**:field-list 的 `Status` 键;缺失则空字符串。

**额外元数据**:`Topic`(非空时保留)。

### 9.5 RFC 解析器

**业务目标**:从 Rust RFC 提案的 Markdown 文件中提取编号、PR 号、Feature Name(用于标题 fallback)。RFC 没有 frontmatter,也没有状态字段。

**编号提取**:从文件名开头的数字提取(RFC 文件名格式是 `{num}-{slug}.md`)。

**PR 号提取**:扫描前 200 行,正则匹配 `RFC PR` 后跟 `#<数字>`(支持 markdown link 形式 `[rust-lang/rfcs#3945](url)` 和 bare 文本形式)。取首个匹配。

**Feature Name 提取**:扫描前 200 行,正则匹配 `- Feature Name: ...` 行。取首个匹配。

**标题 fallback**:对 Feature Name 做 humanize 处理(下划线/连字符转空格,首字母大写);若无 Feature Name 则用文件名 stem。

**状态**:永远为空字符串(规范化时 RFC 总是映射为 ACCEPTED)。

**额外元数据**:`fallback_title`(humanize 后的标题)、`pr_number`(若提取到)。

### 9.6 DEP 解析器

**业务目标**:从 Django DEP 提案文件中解析编号、标题、状态。自动检测文件格式(YAML frontmatter 或 RST field-list)。

**格式检测**:若文件开头(strip 后)以 `---` 开头 → YAML 解析;否则 → RST 解析。

**编号提取**:
- 优先从 `dep`/`DEP` 键提取;从中匹配数字。
- 无该键 → 从文件名 stem 中匹配任意位置的数字。

**标题**(YAML 路径):frontmatter 的 `title` 键。

**标题**(RST 路径):
1. 优先 field-list 的 `Title` 键。
2. 若仍为 None,扫描前 40 行匹配标题行:
   - `DEP {N}: {title}` → 取 title 部分。
   - `DEP {N} {rest}`(rest 非空)→ 取 rest(去掉前导的 `:`/`-`/`–`)。

**状态**:frontmatter/field-list 的 `status` 键;缺失则空字符串。

### 9.7 共享解析原语

#### YAML frontmatter 解析(手写,不用 PyYAML)

**业务目标**:从 Markdown 文件开头的 `---...---` 块中提取键值对。

**规则**:
- 首行必须是 `---`;在 4000 行内找到闭合 `---`。
- 键只允许字母/数字/下划线/连字符;键名小写。
- 值去首尾的 `"` 和 `'`。
- 支持 YAML block list(`- item` 形式):连续的 list 项会被 join 成 `", "`。
- 跳过空行和 `#` 开头的注释行。
- 不支持嵌套 mapping。

#### RST field-list 解析

**业务目标**:从 RST 文件的 field-list(`:Field: value` 形式)或 bare RFC822 风格 header(`Field: value`)中提取键值对。

**规则**:
- 同时支持 bare(`Title: X`)和 RST field-list(`:Title: X`)两种格式。
- 只扫描前 40 行。
- 键名小写且空格转下划线(如 `Last Call` → `last_call`)。
- 支持续行:缩进的行 append 到上一个 field(处理 PEP 的多行 Author)。
- 跳过 RST 标题下划线行(`===`、`---` 等)。
- 见到首个 field-list 后的空行则停止。

---

## 10. 状态处理

### 10.1 状态枚举

提案状态的完整枚举:`draft`、`review`、`accepted`、`final`、`active`、`stagnant`、`deferred`、`withdrawn`、`rejected`、`superseded`、`moved`、`unknown`。

### 10.2 状态集合

- **终态集合** = `{final, active, withdrawn, rejected, superseded, moved, unknown}`
  - 注意 `unknown` 是终态;`draft`/`review`/`accepted`/`stagnant`/`deferred` **不**是终态。
- **通知集合** = `{final, active, accepted, withdrawn, rejected}`

### 10.3 每种类型的原始状态映射

**大小写敏感、空格敏感的精确字符串查找**——不做 `.strip()`/`.lower()`。未知/拼错的状态 → `unknown`。

**EIP/ERC**(共用映射):

| 原始状态 | 规范化状态 |
|---|---|
| `"Draft"` | draft |
| `"Review"` | review |
| `"Last Call"` | review |
| `"Final"` | final |
| `"Living"` | active |
| `"Stagnant"` | stagnant |
| `"Withdrawn"` | withdrawn |
| `"Moved"` | moved |

**PEP**:

| 原始状态 | 规范化状态 |
|---|---|
| `"Draft"` | draft |
| `"Accepted"` | accepted |
| `"Provisional"` | accepted |
| `"Final"` | final |
| `"Active"` | active |
| `"Deferred"` | deferred |
| `"Withdrawn"` | withdrawn |
| `"Rejected"` | rejected |
| `"April Fool!"` | rejected |
| `"Superseded"` | superseded |

**RFC**:空映射(见 §10.4)

**DEP**:

| 原始状态 | 规范化状态 |
|---|---|
| `"Draft"` | draft |
| `"Accepted"` | accepted |
| `"Final"` | final |
| `"Withdrawn"` | withdrawn |
| `"Rejected"` | rejected |
| `"Superseded"` | superseded |

### 10.4 规范化规则

- **RFC**:永远规范化为 `accepted`(RFC 无状态字段,原始状态永远是空字符串)。
- **其他类型**:在对应映射表中精确查找;未命中 → `unknown`。

### 10.5 `should_notify` —— 通知过滤规则

**业务层在派发通知前,必须根据此规则过滤报告。**

| 场景 | 是否通知 |
|---|---|
| 新提案(old_status 为 None) | 是(即使是 draft) |
| 状态未变(old == new) | 否 |
| 状态变化,新状态 ∈ 通知集合(final/active/accepted/withdrawn/rejected) | 是 |
| 状态变化,新状态 ∉ 通知集合(review/stagnant/deferred/moved/superseded/unknown) | 否 |

### 10.6 模板选择规则

根据状态变化选择 AI 分析模板:

| 场景 | 模板 |
|---|---|
| 新提案(old 为 None) | `proposal_new_prompt.j2` |
| 状态未变(内容修改) | `proposal_content_modified_prompt.j2`(用 diff,无 status 上下文) |
| 新状态 ∈ {final, active, accepted} | `proposal_accepted_prompt.j2` |
| 新状态 = rejected | `proposal_rejected_prompt.j2` |
| 新状态 = withdrawn | `proposal_withdrawn_prompt.j2` |
| 新状态 ∈ {deferred, stagnant, moved, superseded, unknown} | `proposal_status_change_prompt.j2`(通用) |

> `should_notify` 和模板选择**独立**——例如 Draft→Stagnant 产 status_change 分析但**不**发通知。

---

## 11. 快照更新与通知过滤的分离(重要设计决策)

### 11.1 设计原则

proposal 业务流程明确分离两个关注点:

1. **快照更新**(tracker 层,在 `check` 内):`Proposal` 表的职责是**忠实记录提案的当前状态**。每次检查时,对所有可解析的变更文件都更新快照(无论该变更是否值得通知)。
2. **通知过滤**(业务层,在 `run` 内 `check` 之后):通知的职责是**按重要性过滤打扰用户**。用 `should_notify` 规则从全部报告中筛出值得通知的子集。

### 11.2 执行顺序

```
tracker.check(kind) 产出全部 ProposalReport(每个可解析变更一个,含 old_status/new_status)
     ↓ tracker 层已完成 upsert_proposal(快照已更新)
业务层(run 内)用 should_notify 过滤 → notifiable 子集
     ↓
notifiable 报告按类型分组、按编号排序,聚合成一条报告落库(report_type="proposal")
     ↓
构造 ProposalEvent 加入 RunResult.events,派发通知
```

### 11.3 为什么这样设计

**如果只更新值得通知的快照(错误做法)**会导致状态脱节:

例如一个提案经历 Draft→Review→Stagnant(三次变化,跨三次运行):
- 若不更新中间态:第 2 次运行时 old=Draft(错误,实际已是 Review),导致 `should_notify` 判断基于错误前提。
- 当前设计(每次都更新快照):每次 old 准确反映上次状态,`should_notify` 判断正确;即使中间态不通知,快照也忠实记录了状态演进。

### 11.4 非 notifiable 报告的处理

- **不落库为报告**:例如 Draft→Review 的变更,tracker 产出了报告,但被 `should_notify` 过滤丢弃,不产生 report 记录。
- **快照已更新**:`Proposal` 表的 raw_status/status 已更新为 Review。
- **这是合理的**:`Proposal` 表是"当前状态快照"而非"历史日志";Draft→Review 这种变化对用户价值低,不值得存储为报告。提案的当前状态始终可从 `Proposal` 表查询。

### 11.5 聚合报告的落库

只有 notifiable 报告被聚合成**一条**报告(`report_type="proposal"`)落库——不是每报告一条。聚合时按类型分组、按编号排序。

---

## 12. RFC 标题特殊解析

### 业务目标

Rust RFC 文件没有结构化标题,但有 `RFC PR: ...#NNN` 行指向对应的 GitHub PR。业务上希望用 PR 标题作为 RFC 的展示标题(比 humanized Feature Name 更有意义)。

### 算法

1. **仅对 RFC 类型**触发;且 GitHub 客户端可用。其他类型或无客户端 → 直接用解析器的 fallback 标题。
2. 从解析结果的 `extra` 中读取 `pr_number`;无 PR 号 → 用 fallback。
3. 从仓库 URL 解析 owner/repo。
4. 调用 GitHub API 查询 PR 标题。
5. **任何失败**(PR 号非数字、网络错误、404、标题为空)→ **用 fallback,永不阻塞追踪**。
6. PR 标题可用 → 替换 parsed 的 title。

**fallback 来源**:解析器的 `fallback_title`(humanized Feature Name 或文件名 stem)。

---

## 13. AI 分析

### 13.1 统一的 AI 调用契约

所有 AI 分析通过统一的接口调用(由 spec 08 定义):传入渲染后的 prompt 字符串,返回结构化的分析结果(含 `summary` 和 `detail` 字段)。

**prompt 构造规则**:prompt 由 Jinja 模板渲染,提案数据(全文或 diff)直接嵌入模板。模型输出经结构化解析(含 `json_repair` 兜底)。

**等价性判定标准**:AI 调用契约的等价性以**模型输入的 token 序列**为准——即合并后的最终文本(指令 + 数据)与旧实现可证明等价。不要求 Python API 签名一致。

**为什么不再有 content/stdin 分离**:旧架构因命令行子进程的参数长度限制分离 prompt 和 content。新架构通过 API 调用,业务数据直接嵌入 prompt。模板中所有"via stdin"措辞必须更新为符合 API 调用方式的表述。

### 13.2 输入数据的两种来源

| 场景 | AI 输入(嵌入 prompt) |
|---|---|
| 状态变化/新增/首次 | 提案全文 |
| 内容修改(状态未变) | `git diff old..new -- <file>` |

### 13.3 失败降级

任何 AI 异常 → 返回空 summary/detail;tracker 存储时空字符串转为 None(`summary or None`)。**追踪永不因 AI 失败阻塞**。上报错误指标(stage="proposal_analysis")。

### 13.4 JSON 解析契约

期望 AI 输出严格 JSON `{"summary": str, "detail": str}`。解析顺序:
1. 贪心正则匹配首个 `{` 到末个 `}`。
2. `json.loads`。
3. 失败 → `json_repair` 修复后重试;非 dict → 抛异常。
4. `summary`/`detail` 任一为空 → 抛异常。

### 13.5 7 个 prompt 模板

都 `{% extends "proposal_prompt_base.j2" %}`。base 模板包含:
- `{% block task %}`(子模板覆盖)
- 语言要求(output language = `{{ language }}`)
- `{% block source %}` 默认 "full proposal text"(措辞更新,不再用 stdin)
- 提案上下文(Kind/Number/Title,可选 Old/New status)
- "CRITICAL FORMAT REQUIREMENTS":只输出 JSON `{"summary": "...", "detail": "..."}`
- `{% block content_requirements %}`(子模板覆盖)

| 模板 | 触发条件 | task |
|---|---|---|
| `proposal_new_prompt.j2` | old=None | 分析新提案 |
| `proposal_accepted_prompt.j2` | new ∈ {FINAL, ACTIVE, ACCEPTED} | 分析被接受/最终化 |
| `proposal_rejected_prompt.j2` | new=REJECTED | 分析被拒绝 |
| `proposal_withdrawn_prompt.j2` | new=WITHDRAWN | 分析被撤回 |
| `proposal_status_change_prompt.j2` | new ∈ {DEFERRED, STAGNANT, MOVED, SUPERSEDED, UNKNOWN} | 状态变更分析 |
| `proposal_content_modified_prompt.j2` | old==new | 基于 git diff 分析修改;source block 改为"以下是 git diff";无 status_context |

---

## 14. 报告生成与落库

### 14.1 ProposalReport 数据结构

tracker 产出的内存中间结构:

| 字段 | 业务含义 |
|---|---|
| `kind` | 提案类型 |
| `number` | 编号 |
| `title` | 标题(可能为 None) |
| `old_status` | 旧状态(新提案为 None) |
| `new_status` | 新状态 |
| `file_path` | 文件相对路径 |
| `file_url` | GitHub blob URL |
| `commit_hash` | 当前 commit |
| `analysis_summary` | AI 摘要(失败或删除时为 None) |
| `analysis_detail` | AI 详情(失败或删除时为 None) |

### 14.2 聚合报告模板(`proposal_events_report.j2`)

渲染 **notifiable** 报告的聚合:
- 按类型分组;每组内按编号排序。
- 每类型:二级标题含指向 tracker 仓库的链接(若有 tracker_url,否则纯文本 `{KIND | upper}`)。
- 每报告:三级标题——**4 级 fallback**:
  1. 有 title 且有 file_url → `### [{title}]({file_url})`
  2. 有 title 无 file_url → `### {title}`
  3. 无 title 有 file_url → `### [#{number} {file_name}]({file_url})`
  4. 无 title 无 file_url → `### #{number} {file_name}`
- 小标签(精确格式):`<small>#️⃣ #{number} · 📌 {old_status.value} → {new_status.value} · 📄 {file_name}</small>`;若是新提案(old_status 为 None)则状态部分为 `{new_status.value} ({new})`。
- AI 摘要:`{analysis_summary or _("No summary available.")}`
- **详情块总是渲染**:`<details><summary>{Click to view detailed analysis}</summary>\n\n{analysis_detail or _("No detailed analysis available.")}\n\n</details>`(即使 analysis_detail 为空也渲染,用 fallback 文本)。
- **双层分隔符**:内层(同 kind 内 reports 间)`---`;外层(kinds 间)`---`(前有空行)。
- 结尾 `{{ footer(generation_time) }}`。

### 14.3 聚合报告落库

notifiable 报告聚合后,落库为一条 Report 行:

| 字段 | 值 |
|---|---|
| `report_type` | `"proposal"` |
| `commit_count` | notifiable 报告数(`len(reports)`) |
| `title` | AI 生成(fallback `"Proposal Updates"`) |
| `content` | 渲染后的聚合报告内容 |

落库后经 MarkPost 发布(若配置),详见 spec 09。

---

## 15. 通知事件

### 15.1 事件触发

**仅对 notifiable 报告**构造通知事件(已经过 §10.5 的 `should_notify` 过滤)。每个 notifiable 报告构造一个 `ProposalEvent`。

### 15.2 事件内容(proposal 通知的 payload 与其他类型不同)

proposal 通知携带的数据**不同于** changelog/discovered——它不携带 summary/repo_statuses,而是携带文件名列表:

| 事件字段 | 取值 |
|---|---|
| `proposal_kind` | 类型字符串 |
| `number` | 编号(int) |
| `title` | 标题(空字符串若 None) |
| `status` | 新状态字符串 |
| `url` | 文件 URL |
| `summary` | AI 摘要(空字符串若 None) |

**通知 payload 派生**:dispatcher 从所有 ProposalEvent 派生:
- `filenames`:最多 **5 个**文件名(`PurePath(file_path).name`)
- `more_count`:`max(0, len(notifiable reports) - 5)`
- `markpost_url`:聚合报告的 MarkPost URL
- `title`:聚合报告的 AI 生成 title

### 15.3 通知模板与格式

通知模板 `templates/notifications/proposal/{plain_text, html, card_json}.j2`:

| 通道 | 格式 |
|---|---|
| 纯文本(console) | 标题 + 空行 + 每文件 `📄 {filename}`(最多 5 个)+ `... and {N} more`(若 more_count > 0)+ 空行 + markpost URL |
| HTML(email) | `Subject: {escaped title}\n\n<html><body><h2>{escaped title}</h2><ul>[<li>📄 {escaped fname}</li>][<li>... and {N} more</li>]</ul>[<p><a href="{markpost}">{View Detailed Report}</a></p>]</body></html>`(注意 email 有 Subject 行) |
| 卡片 JSON(feishu) | 每文件一个 `div` 含 `📄 {fname}`(lark_md),文件间 `<hr>`,more_count > 0 时 `... and {N} more` div;**无** `_Generated by Progress_` footer(与 changelog/discovered 不同);`card_link` = markpost URL(若存在);header template "blue" |

### 15.4 事件派发

事件加入 `RunResult.events`,经 `core.py` 的 `run_notifications` 统一派发(详见 spec 10)。

### 15.5 通道配置边界

- 通道配置由 spec 02/10 定义,核心统一管理。
- integration 不关心通道,只产出事件。详见 spec 10。

---

## 16. 必需的底层 git 操作

以下操作必须由共享的 git 工具层(`cli/git/`)提供:

| 操作 | 业务含义 |
|---|---|
| clone(单分支、指定分支) | 首次克隆提案仓库 |
| fetch + reset | 更新已有克隆 |
| 清理 `.git/*.lock` | fetch 前的自愈 |
| 读取当前 HEAD | 获取最新 commit |
| 读取变更文件状态列表 | `git diff --name-status old..new`,解析为 `[(status, path)]` |
| 读取单文件 diff | `git diff old..new -- <file>`(内容修改路径用) |
| 读取文件创建时间 | `git log --diff-filter=A --format=%ai -1 -- <file>`(首次检查选最新用) |

---

## 17. 边界行为与 edge cases

### 数据流与控制流
| 场景 | 期望行为 |
|---|---|
| 首次运行(checkpoint 为 None) | 全部提案入库,只返回 1 个报告(最新创建的) |
| 无新提交(HEAD == checkpoint) | 盖戳检查时间戳,返回空 |
| 提案目录不存在 | 盖戳 checkpoint,返回空 |
| 无匹配文件 | 盖戳 checkpoint,返回空 |
| 提案文件解析失败(如 PEP `TBD`) | 记 debug 日志,跳过该文件,不影响其他 |
| 单类型异常 | 被吞掉(记 warning),不影响其他类型 |
| clone 失败 | 业务异常 → 上报错误(stage="clone")→ 重抛 |

### 状态转换(每条都要测试)
| 场景 | 模板 | notify? |
|---|---|---|
| 新提案(old=None) | proposal_new_prompt.j2 | 是 |
| Draft→Final | proposal_accepted_prompt.j2 | 是 |
| Draft→Review | proposal_status_change_prompt.j2 | 否 |
| Draft→Withdrawn | proposal_withdrawn_prompt.j2 | 是 |
| Draft→Stagnant | proposal_status_change_prompt.j2 | 否 |
| Review→Final | proposal_accepted_prompt.j2 | 是 |
| Final→Final(内容修改) | proposal_content_modified_prompt.j2(用 diff) | 否 |
| Draft→Moved | proposal_status_change_prompt.j2 | 否 |
| 未知原始状态 | normalize=unknown → proposal_status_change_prompt.j2 | 否 |

### 快照与通知分离
| 场景 | 快照更新 | 报告落库 | 通知 |
|---|---|---|---|
| Draft→Review(非 notifiable) | 是(更新为 review) | 否(被过滤) | 否 |
| Draft→Final(notifiable) | 是(更新为 final) | 是(聚合落库) | 是 |
| 内容修改(状态未变) | 是(刷新 title/raw_status) | 否(被过滤) | 否 |
| 新提案 | 是(新建行) | 是(若通过 should_notify) | 是 |

### 移动与删除
| 场景 | 期望行为 |
|---|---|
| 文件重命名(同编号 delete+add) | 识别为移动(delete 被 skip),只处理 add |
| 非终态提案被删 | status 改 withdrawn,产报告(无 AI 分析) |
| 终态提案被删 | status 不变,产报告(无 AI 分析) |
| 未知编号文件被删 | 忽略(返回 None) |

### RFC 特殊解析
| 场景 | 期望行为 |
|---|---|
| RFC 有 PR 号,PR 标题可用 | report/DB 用 PR 标题 |
| RFC 有 PR 号,PR 标题为空 | 用 fallback(humanized Feature Name) |
| RFC PR 查询抛异常 | 用 fallback,不阻塞追踪 |
| RFC 无 PR 号 | 用 fallback |
| RFC 无 Feature Name | title = 文件名 stem |
| 非 RFC 类型 | 直接用解析器标题,不触发 PR 解析 |

### AI 分析
| 场景 | 期望行为 |
|---|---|
| AI 返回正常 JSON | report 分析字段填充 |
| AI 超时/异常 | 返回空,report 分析字段为 None |
| AI 返回畸形 JSON | json_repair 修复;仍失败 → 异常 → 空 |
| 内容修改路径 | 用 git diff(非全文)作 AI 输入 |

### Clone 与自愈
| 场景 | 期望行为 |
|---|---|
| 首次 clone | `git clone --single-branch --branch <branch>` |
| 已存在且健康 | fetch+reset + 验证 → 复用 |
| corrupt HEAD | 验证失败 → 删除目录 → 重新 clone |
| clone 失败 | 业务异常 → 上报错误 → 重抛 |
| clone 超时 | git 操作超时的 2 倍 |

### 解析器边界
| 场景 | 期望行为 |
|---|---|
| EIP/ERC frontmatter 无 title(Moved stub) | title=None |
| EIP `eip:` 带前导零(`eip: 007`) | number="7" |
| PEP `:Author:` 多行续行 | 续行 append,Author 字段完整 |
| PEP `PEP: TBD` | 解析异常(唯一抛异常的解析器) |
| PEP 深层 headers(Author 后跟多行续行) | Title 仍能正确解析 |
| RFC markdown link 形式 `#NNN` | pr_number 正确提取 |
| DEP .md(YAML)vs .rst(RST)自动检测 | 分发到对应解析路径 |
| DEP RST 标题 `DEP N: title` | title 从标题行解析 |
| DEP 文件名 `0014-background-workers.rst` + header `:DEP: 14` | number 用 header(14) |
| DEP 无数字文件(`content-negotiation.rst`) | number="" |

### 配置/状态
| 场景 | 期望行为 |
|---|---|
| PUT /config/proposal 修改后 | DB config 表更新,ProposalTrackerState 表不变,下次 run 时 sync |
| 类型从 config 移除 | GC 删除 ProposalTrackerState(CASCADE 删 Proposal) |

---

## 18. 并发、超时、重试

| 项 | 值 |
|---|---|
| 检查并发 | `run(concurrency=...)`,默认 1(串行);>1 时用信号量;单类型异常被吞 |
| clone 超时 | git 操作超时的 2 倍 |
| clone 重试 | 无(失败即重抛;但自愈机制是一次"软重试") |
| git lock 自愈 | fetch+reset 内部清理 `.git/*.lock` |
| GitHub PR 查询重试 | tenacity 重试 5xx/RateLimit;404 → 降级到 fallback |
| AI 分析 | 复用统一 AI 接口的重试/超时;失败降级为空 |
| AI 全局并发 | `AI_CONCURRENCY=1`(全局信号量,序列化所有 AI 调用) |
| 单类型失败对其他类型 | 无影响(异常被吞) |

---

## 19. 测试矩阵(验收清单)

### 解析器单测
- [ ] EIP:标准 frontmatter / Moved stub(title=None)/ `eip:` 前导零 / extract_number 匹配 eip- 和 erc- 前缀 / category+type extra
- [ ] PEP:标准 RST / 多行 Author 续行 / `PEP: TBD` 抛异常 / 深层 headers / Topic extra
- [ ] RFC:markdown link PR 号 / Feature Name humanize / 无 PR / 无 Feature Name(title=stem)/ raw_status 永远空
- [ ] DEP:YAML 变体 / RST 变体 / RST 标题 fallback / header number vs 文件名 number / 无数字文件
- [ ] YAML frontmatter 解析:键小写 / 值去引号 / block list join / comment 跳过 / 4000 行上限
- [ ] RST field-list 解析:bare 与 RST 两种格式 / 续行 append / 空格转下划线 / 40 行上限

### 状态单测
- [ ] normalize:每类型每映射(EIP Last Call→review、Living→active;PEP April Fool!→rejected、Provisional→accepted;RFC 总是 accepted;未知→unknown)
- [ ] should_notify 矩阵全分支(None→是 / 相同→否 / 新状态∈通知集合→是 / 新状态∉通知集合→否)
- [ ] 模板选择全分支(new/content_modified/accepted×3/rejected/withdrawn/generic×5)

### 快照与通知分离(关键)
- [ ] Draft→Review:快照更新为 review,报告不落库,不通知
- [ ] Draft→Final:快照更新为 final,报告聚合落库,通知
- [ ] 内容修改(状态未变):快照刷新,报告不落库,不通知
- [ ] 新提案:快照新建行,报告聚合落库(若通过 should_notify),通知
- [ ] 跨次运行的状态演进(Draft→Review→Final):每次 old_status 准确反映上次状态

### 检查单测
- [ ] 首次运行:全部入库 + 只产 1 个报告(最新创建的)
- [ ] 增量:Draft→Final 产报告 + new_status=final
- [ ] 同 commit:返回空
- [ ] 文件删除:非终态 → withdrawn;终态 → 不变;未知编号 → None
- [ ] 文件移动(同编号 delete+add):delete 被 skip,只处理 add
- [ ] 解析失败文件:跳过不崩溃
- [ ] AI 失败:report 仍产出,分析字段为 None
- [ ] RFC PR 标题解析:可用/空/异常 三种 fallback
- [ ] ERC branch=master
- [ ] language 传播到 prompt
- [ ] clone 失败:上报错误 + 重抛
- [ ] corrupt HEAD 自愈:验证失败 → 删除 → 重新 clone → 成功
- [ ] 健康复用:不重新 clone
- [ ] 文件过滤:目录前缀 + basename 模式匹配
- [ ] 移动检测:基于编号

### 集成与通知
- [ ] notifiable 报告聚合成一条报告落库(report_type="proposal", commit_count=len(notifiable))
- [ ] 聚合报告按类型分组、按编号排序
- [ ] 聚合报告模板:4 级标题 fallback / 小标签精确格式 / 详情块总是渲染 / 双层分隔符
- [ ] ProposalEvent 只对 notifiable 报告构造
- [ ] 通知 payload 派生 filenames(最多 5)+ more_count
- [ ] 3 个通知模板可达且渲染正确(console 📄 / email 带 Subject / feishu 无 footer)
- [ ] 检查并发参数可调(默认 1 串行;>1 信号量)
- [ ] sync:类型新增/移除(CASCADE 删 Proposal)
- [ ] sync 只在 run 时触发,PUT /config 不触发
- [ ] 内容修改用 git diff(非全文)作 AI 输入
