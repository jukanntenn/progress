# repo · 仓库与 Release 跟踪

> 本规范定义 repo integration 的**完整业务行为**。读者对象:实现者、审查者、后续维护者。规范即验收标准——每一条"必须"都应对应可通过的测试。

## 1. 业务概述

repo integration 跟踪 GitHub 仓库的活动,产生三类业务输出:

1. **Commit 跟踪**:对每个配置的仓库,clone/fetch 代码,计算自上次检查以来的 commit diff,调用 AI 分析变更,生成报告。
2. **Release 跟踪**:对每个配置的仓库,查询 GitHub Releases API,识别自上次检查以来新增的 release,计算 release 之间的代码 diff,调用 AI 分析,生成报告。
3. **Owner 自动发现**:对每个配置的 GitHub owner(用户或组织),枚举其名下的仓库,发现自上次检查以来**新创建**的仓库,拉取其 README,调用 AI 分析,产出"发现新仓库"通知事件。

### 业务流程

1. **配置同步**(`sync`):把 config 中的 repos 和 owners 分别同步到状态表(upsert + GC)。
2. **逐仓库检查**(`run` 步骤 A+B):对每个启用的仓库执行检查——clone/fetch、release 跟踪、commit diff 分析、推进 checkpoint。
3. **逐 owner 发现**(`run` 步骤 C):对每个启用的 owner 执行发现——枚举仓库、识别新增、拉取 README、AI 分析、产出 DiscoveredRepoEvent。
4. **生成报告与通知**:
   - 仓库检查结果(reports)经 reports pipeline 聚合,落库为一条 `report_type="repo_update"` 的聚合报告(简化:不再每 repo 单独落库),经 batch 切分按 batch 派发 ReportEvent。
   - owner 发现结果(events)直接产出 DiscoveredRepoEvent,聚合落库为一条 `report_type="repo_new"`,派发到通知通道。

### 关键业务规则

1. **commit checkpoint 与 release checkpoint 完全独立**——一次运行可能只推进其中一个。两者是正交维度:commit 反映日常代码变更,release 反映版本发布。重置其中一个不影响另一个(这是预期行为,便于用户独立管理两者的回溯)。
2. **release 跟踪失败不阻塞 commit 跟踪**——release 异常被捕获后继续到 commit 分析。
3. **首次 commit 检查只分析最近 N 个 commit**(默认 3,可配置),不分析全部历史——控制 AI 成本和首次运行时间。**注意**:其他对象(release/owner/changelog/proposal)首次都只报 1 个,只有 repo commit 报 N 个——因为 commit 是连续流(需要 lookback 提供上下文),其他是离散事件(1 个就够通知)。
4. **首次 release 检查只上报最新的 1 个 release**——避免首次运行刷屏。
5. **首次 owner 发现只上报最新的 1 个仓库**——避免首次运行刷屏。
6. **owner 发现的仓库不自动加入 Repository 表**——只产生通知事件,不自动开始跟踪。用户需手动将感兴趣的仓库加入 config。
7. **owner 发现的仓库若已在 Repository 表中则跳过**(去重)——避免对已跟踪仓库重复发送"发现"通知。**此为已接受的改进**(原行为不去重)。
8. **并发可配置**——`run` 接受 `concurrency` 参数(默认 1 串行)。仓库检查支持并发;owner 发现默认串行。**注意**:AI 调用受全局信号量约束(`AI_CONCURRENCY=1`,见 spec 08),并发主要对非 AI 工作(git/HTTP)生效。
9. **config 修改后状态表不立即同步**——`sync` 只在 `run` 流程开始时执行(详见 spec 06)。

---

## 2. 数据模型

### `Repository`(表 `repositories`)

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `name` | CharField(255) | required | — | `owner/repo` 形式(由 URL 派生) | — |
| `url` | CharField(255) | **unique** | — | 规范化后的仓库 URL;**身份键** | — |
| `branch` | CharField(255) | required | — | 跟踪的分支 | — |
| `enabled` | BooleanField | — | True | false 时检查跳过 | — |
| `last_commit_hash` | CharField(255) | nullable | None | commit checkpoint | None:该仓库从未成功完成过 commit 分析(首次跟踪) |
| `last_check_time` | DatetimeField | nullable | None | 上次成功 commit 分析的时间 | None:该仓库从未成功完成过 commit 分析 |
| `last_release_tag` | CharField(255) | nullable | None | release checkpoint(最新处理过的 release tag) | None:该仓库从未成功处理过任何 release |
| `last_release_commit_hash` | CharField(255) | nullable | None | `last_release_tag` 对应的 commit SHA,用于 release diff | None:该仓库从未成功处理过任何 release(与 `last_release_tag` 同生同灭) |
| `last_release_check_time` | DatetimeField | nullable | None | release checkpoint 时间戳 | None:该仓库从未执行过 release 检查(首次 release 检查时只上报最新 1 个 release) |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | `updated_at` 由 `BaseModel` 自动刷新 | — |

### `GitHubOwner`(表 `github_owners`)

| 字段 | 类型 | 约束 | 默认 | 业务含义 | None 语义 |
|---|---|---|---|---|---|
| `id` | IntField | PK | — | — | — |
| `owner_type` | CharField(255) | required | — | `"organization"` 或 `"user"` | — |
| `name` | CharField(255) | required | — | GitHub login | — |
| `enabled` | BooleanField | — | True | false 时发现流程跳过 | — |
| `last_check_time` | DatetimeField | nullable | None | 上次发现检查的时间(无论是否发现新仓库都盖戳) | None:该 owner 从未执行过发现检查 |
| `last_tracked_repo` | DatetimeField | nullable | None | 已知仓库的创建时间水位 | None:该 owner 从未执行过发现检查(首次发现时只上报最新 1 个仓库) |
| `created_at` / `updated_at` | DatetimeField | — | `now_utc` | — | — |

**唯一约束**:`unique_together = (("owner_type", "name"),)`。

### 字段语义精确说明

**`url` 规范化**:存储前必须经过规范化:`owner/repo` 简写展开为 `https://github.com/owner/repo.git`(或 SSH 形式)。规范化后的 URL 是 upsert/GC/dedup 的键。

**两组 checkpoint 的独立性**(重要设计决策,已文档化):
- `last_commit_hash` + `last_check_time` 构成 commit checkpoint。
- `last_release_tag` + `last_release_commit_hash` + `last_release_check_time` 构成 release checkpoint。
- 一次检查中两者分别在不同代码路径推进,互不依赖。
- 一个仓库可能只有新 commit 无新 release(只推进 commit checkpoint),反之亦然。
- 用户若手动重置 commit checkpoint(如想重新分析),release checkpoint 不会跟着重置——这是预期行为,因为两者代表正交的业务维度。

---

## 3. 配置

### `RepoItemConfig`(单个仓库配置)

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `url` | str | 是 | — | 接受 `owner/repo`、`https://...`、`git@host:owner/repo.git` |
| `branch` | str | 否 | `"main"` | 跟踪分支 |
| `enabled` | bool | 否 | True | — |
| `protocol` | `Literal["https", "ssh"]` | 否 | `"https"` | per-repo 协议覆盖 |

URL 校验模式(满足任一即可):
- `^[\w-]+/[\w-]+$`(owner/repo 简写)
- `^https?://`
- `^git@[\w.-]+:[\w-]+/[\w-]+\.?git?$`(SSH)

### `OwnerItemConfig`(单个 owner 配置)

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `type` | `Literal["organization", "user"]` | 是 | — | owner 类型(TOML 键名是 `type`) |
| `name` | str | 是 | — | GitHub login(stripped 后非空) |
| `enabled` | bool | 否 | True | — |

### `RepoIntegrationConfig`(integration 顶层配置)

| 字段 | 类型 | 默认 |
|---|---|---|
| `repos` | `list[RepoItemConfig]` | `[]` |
| `owners` | `list[OwnerItemConfig]` | `[]` |
| `first_run_lookback_commits` | int(ge=1) | 3 |

所有配置类 `extra="forbid"`。配置从 DB config 表(section=`"repo"`)读取,读不到时回退全默认。

---

## 4. 插件生命周期

### `setup`
接收共享依赖(CoreConfig 和共享的 aiohttp ClientSession)。从 DB 读取 `RepoIntegrationConfig`,失败回退默认。

仅当 `cfg.github.gh_token` 非空时,构造 GitHub API 客户端;token 为空则客户端为 None 并记录 warning。token 为空时:配置同步仍运行(不需要 token),但检查中的 release 跟踪和 owner 发现会跳过(它们需要 GitHub API)。

### `sync` —— 配置同步

#### repos 同步

1. 计算期望的 URL 集合(来自 config 的所有仓库 URL,**含 disabled 的**,用于 GC 判定)。
2. 对每个 config 仓库:
   - 规范化 URL;从 URL 派生 `owner/repo` 形式的 name。
   - 若 DB 中不存在该 URL → 创建新行(checkpoint 字段都初始化为 None),计入"新增"。
   - 若 DB 中已存在 → 比较 `name`/`branch`/`enabled`(以及 `url`);任一变化则更新,计入"更新"。
3. **GC**:DB 中存在但不在期望 URL 集合中的行 → 删除(checkpoint 丢失),计入"删除"。

#### owners 同步

1. 计算期望的 `(owner_type, name)` 集合。
2. 对每个 config owner:
   - 若 DB 中不存在该 key → 创建新行(`last_check_time` 和 `last_tracked_repo` 都初始化为 None),计入"新增"。
   - 若 DB 中已存在 → **仅**比较 `enabled`(`owner_type`/`name` 是 key,不覆盖);变化时更新 `enabled`,计入"更新"。
3. **GC**:DB 中存在但不在期望集合中的行 → 删除,计入"删除"。

> owners 同步**只更新 enabled 字段**,不像 repos 同步会更新多个字段——因为 owner 除了 enabled 没有其他可变业务字段。

**sync 的触发时机**:只在 `run` 流程开始时执行。`PUT /api/v1/config/repo` 成功后只写 DB config 表,**不**调用 sync(详见 spec 06)。

### `run(*, concurrency: int = 1)` —— 执行检查与发现

#### 步骤 A+B:每个启用仓库的 release + commit 跟踪

对每个启用的仓库(支持并发,用 `concurrency` 控制):

1. **Release 跟踪**(独立于 commit,先执行):查询 GitHub Releases,识别新增 release,AI 分析(详见 §6)。失败不阻塞 commit。
2. **Commit diff 分析**:clone/fetch、计算 diff、AI 分析(详见 §5)。
3. 把结构化的检查结果(`RepositoryReport`)加入 `RunResult.reports`(通过 `ReportSection.payload` 承载)。

#### 步骤 C:每个启用 owner 的自动发现

仅当 GitHub 客户端可用时,对每个启用的 owner(**串行**,不并发):

1. 枚举 owner 名下的仓库(详见 §7)。
2. 识别新增仓库(基于创建时间水位)。
3. 对每个新增仓库:**若已在 Repository 表中则跳过**(去重);否则拉取 README、AI 分析、构造 `DiscoveredRepoEvent`。
4. 发现事件累积后,聚合成一条 `report_type="repo_new"` 的报告落库 + 派发 DiscoveredRepoEvent 到通知通道。

#### 错误聚合

- 单个仓库或 owner 的业务异常 → 计入 `RunResult.errors`,整体状态降为 `partial`。
- 其他意外异常 → 包装为业务异常后同上。
- 若有错误且无任何成功报告 → 整体状态降为 `failed`。

**并发模型**:
- **仓库检查**:支持 `concurrency` 参数(默认 1)。并发度大于 1 时用信号量限制同时检查的仓库数。每个并发任务必须传播父 OTel context(保持 trace 连续性)。
- **owner 发现**:**串行**(不并发)。
- **单仓库内的 release 分析**:串行(逐个 release 分析)。
- **AI 调用的全局序列化**:AI 请求受全局信号量约束(`AI_CONCURRENCY=1`,见 spec 08),并发主要对 git/HTTP 工作生效。

### `teardown`
释放引用。共享的 ClientSession 由上层 lifespan 管理,不在此关闭。

---

## 5. Commit 跟踪

### 5.1 单仓库处理流程

1. **Release 跟踪**(独立于 commit,先执行):
   - 执行 release 检查(详见 §6)。
   - 若有结果:按发布时间降序排序,逐个 AI 分析,推进 release checkpoint 到最新的那个。
   - 任何异常:记错误日志,**继续**到 commit 分析。
2. **Clone/fetch**:首次 clone,后续 fetch+reset。clone 失败重试 3 次(指数退避)。
3. **计算 diff**:基于 commit checkpoint 决策(详见 §5.2)。
4. **无新 commit 且无新 release**:跳过该仓库。
5. **有新 commit**:AI 分析 diff,推进 commit checkpoint。
6. **diff 为空字符串**(strip 后):不推进 commit checkpoint,跳过 commit 分析。
7. 把结构化的检查结果(`RepositoryReport`)塞入 `ReportSection.payload`。

### 5.2 diff 决策树

1. clone/fetch 后读取当前 HEAD。
2. 若 HEAD 与 commit checkpoint 相同 → 无新 commit,返回 None。
3. 若 commit checkpoint 为 None(首次检查)→ 执行首次检查 diff 策略。
4. 否则 → 执行增量 diff 策略。

### 5.3 首次检查策略选择

读取配置的回溯数(`first_run_lookback_commits`,默认 3)和仓库总 commit 数:

- 总 commit 数为 0(空仓库)→ 返回 None。
- 计算有效回溯数 = min(回溯数, 总 commit 数)。
- **总 commit 数 > 有效回溯数**(历史充足)→ **range 策略**:取 `HEAD~{有效回溯数}` 作为起点,分析该范围内的 commit。
- **总 commit 数 ≤ 有效回溯数**(历史不足)→ **recent 策略**:取最近 N 个 commit,起点为其中最老的。

策略选择依据:range 策略需要 `HEAD~N` 存在;当仓库历史不足 N 时回退到 recent 策略。

### 5.4 增量策略

起点为已保存的 commit checkpoint,终点为当前 HEAD。

**硬上限**:增量范围内的 commit 数被常量 `MAX_INCREMENTAL_COMMITS`(默认 50,代码常量不可配置)截断。当范围内 commit 数超过上限时(典型场景:仓库从长时间失败中恢复、被禁用很久后重新启用、或上游突然爆发大量提交),只分析最近的 `MAX_INCREMENTAL_COMMITS` 个 commit(改用 `HEAD~{上限}..HEAD` 范围),checkpoint 仍推进到 HEAD——超出上限的较老 commit 被跳过,以约束 AI 成本与运行时间。该上限适用于任何增量爆发,不依赖 stale 判定。

### 5.5 统一的 diff 结果结构

所有策略返回统一的结构(或 None 表示无新 commit):

| 字段 | 业务含义 |
|---|---|
| `diff` | diff 文本 |
| `previous_commit` | 起点 commit(首次检查时为本次分析的最老 commit) |
| `commit_count` | 本次分析的 commit 数 |
| `commit_messages` | commit message 列表 |
| `is_range_check` | 是否为 range 策略(首次检查的 recent 策略为否,其他为是) |

### 5.6 必需的底层 git 操作

以下操作必须由共享的 git 工具层(`cli/git/`)提供:

| 操作 | 业务含义 |
|---|---|
| clone(带分支、带 tags、单分支) | 首次克隆仓库 |
| fetch + reset | 更新已有克隆到最新 |
| 读取当前 HEAD | 获取最新 commit hash |
| 读取第一父提交 | 回退用(range 策略中 `HEAD~N` 不存在时) |
| 读取 `HEAD~N` | range 策略的起点 |
| 读取最近 N 个 commit hash | recent 策略 |
| 读取 commit message 列表(范围或最近 N) | 报告展示 |
| 读取 commit patch(最近 N) | recent 策略的 diff |
| 读取 commit diff(范围) | range/incremental 策略的 diff |
| 读取 commit 数(范围或全部) | 策略选择和报告统计 |
| 清理 `.git/*.lock` 文件 | fetch 前的自愈(避免 lock 冲突) |

---

## 6. Release 跟踪

### 6.1 业务目标

对每个仓库,查询 GitHub Releases,识别自上次 release 检查以来新增的 release,为每个新增 release 计算与上一个 release 之间的代码 diff,调用 AI 分析,推进 release checkpoint。

### 6.2 release 检查算法

1. 查询仓库的所有 release(GitHub Releases API)。
2. **过滤掉 draft 和 prerelease**——只处理正式 release。
3. 空列表 → 返回 None(无 release 可处理)。
4. 规范化 release checkpoint 时间戳(`last_release_check_time`):
   - 若是字符串 → 解析;失败置 None。
   - 若是 naive datetime → 强制加 UTC 时区。
5. 判断是否首次检查(checkpoint 时间戳为 None)。
6. 构建候选列表:
   - 对每个 release,解析其 `published_at`;解析失败的跳过。
   - **首次检查**:所有有效 `published_at` 的 release 中,取最新的那一个。
   - **增量检查**:收集所有 `published_at > checkpoint 时间戳` 的 release(严格大于)。
7. 候选为空 → 返回 None。
8. 为每个候选 release hydrate:
   - 查询该 release tag 对应的 commit SHA;失败则 commit hash 为 None(不阻塞)。
   - release notes 为 None 时用空字符串。

### 6.3 release checkpoint 推进

分析完成后,按 `published_at` 降序排序(确保最新的在首位),推进 checkpoint:
- `last_release_tag` = 最新候选的 tag
- `last_release_commit_hash` = 最新候选的 commit SHA
- `last_release_check_time` = 当前时间

### 6.4 release 分析算法

对排序后的每个 release:
1. **计算 release diff**(仅增量检查且存在上一个 release commit 时):
   - diff 起点 = `last_release_commit_hash`(上一个 release 的 commit)
   - diff 终点 = 当前 release 的 commit
   - 起点或终点为空 → 不计算 diff;计算失败 → 记 warning,diff 为 None(不阻塞)。
2. **AI 分析**(详见 §8):传入 release 数据(tag、标题、notes、发布时间、commit hash、diff 内容)。
3. **失败降级**:AI 异常 → 该 release 的 summary 为 fallback 文案(`**AI analysis unavailable for {tag}**`),detail 为空;上报错误指标;**继续处理其他 release**。
4. 保留 release 的所有原始字段(通过字段合并,不丢弃额外字段)。

### 6.5 GitHub API 层的 release 支持

GitHub API 客户端的 release 数据结构必须包含:`tag`、`name`(标题,可能 None)、`body`(notes,可能 None,业务上视为空字符串)、`published_at`(发布时间,**必需**)、`prerelease`(过滤用)、`draft`(过滤用)、`url`。

GitHub API 客户端必须提供:
- 遍历仓库所有 release 的方法,**自动过滤 draft 和 prerelease**。
- 根据 tag 查询 release 对应 commit SHA 的方法。

**GitHub API 错误处理**:404 → 空结果或 None(不抛);RateLimit / 5xx → 重试(tenacity),最终失败抛业务异常。

### 6.6 release diff 截断

AI 分析前,对 release diff 内容截断:
- 阈值 = `cfg.analysis.max_diff_length`(默认 100_000 字符)。
- 超过 → 截断到阈值,标记 `truncated=True`,记录 warning。
- 截断信息传入 AI prompt 模板。

---

## 7. Owner 自动发现

### 7.1 业务目标

对每个 owner,枚举其名下的所有仓库,识别自上次检查以来**新创建**的仓库,为每个新仓库拉取 README 并 AI 分析,构造发现事件。水位是"已见仓库的最新创建时间"。

### 7.2 发现算法

1. 枚举 owner 名下的所有仓库(按 owner_type 路由到 `/orgs/{owner}/repos` 或 `/users/{owner}/repos`,自动分页)。
2. **过滤掉 fork 仓库**——只关注原创仓库。
3. 枚举失败 → 记错误,返回空。
4. 对每个仓库解析 `created_at`;解析失败的跳过。
5. 若无有效仓库 → 返回空。
6. 按创建时间升序排序;记录最新创建时间。
7. 读取水位(`last_tracked_repo`);若是字符串则解析。
8. **首次发现**(水位为 None)→ 候选 = 最新的 1 个仓库。
9. **增量发现**(水位存在)→ 候选 = 所有创建时间严格大于水位的仓库。
10. **无论是否有候选**:盖戳 `last_check_time` 和 `last_tracked_repo`(推进到最新创建时间,**不是**候选中的最新——保证下次不会重复发现)。
11. 对每个候选仓库执行 `process_new_repo`(详见 §7.3)。

**关键规则**:
- **盖戳总是发生**(即使无候选)——`last_check_time` 和 `last_tracked_repo` 都推进到最新值。
- `last_tracked_repo` 推进到当前列表中最新仓库的创建时间,确保下次只发现真正更新的仓库。

### 7.3 单个候选仓库的处理

1. **去重检查(已接受的改进)**:若该仓库的 URL 已在 Repository 表中 → 跳过(不作为"发现"上报)。业务语义:"发现"特指"用户尚未跟踪的新仓库"。
2. 从仓库信息提取:full name、name、description、created_at、html_url。
3. **拉取 README**:
   - 成功 → 标记 has_readme=True。
   - 404 → has_readme=False,**不**记 warning(README 不存在是正常的)。
   - 其他失败 → has_readme=False,记 warning。
4. **跳过无 README 的仓库**——无 README 的仓库对用户价值低,不上报。
5. **README 截断**:超过 50_000 字符则截断,标记 truncated。
6. **AI 分析 README**(详见 §8):失败 → fallback summary/detail,仍上报该仓库。
7. 构造 `DiscoveredRepoEvent`。

### 7.4 GitHub API 层的 owner 发现支持

GitHub API 客户端的仓库信息数据结构必须包含:`owner`、`name`、`full_name`、`default_branch`、`description`(可能 None)、`html_url`、`created_at`(**必需**)、`fork`(过滤用)、`archived`。

`list_owner_repos(owner, owner_type)` 方法按 owner_type 路由到对应 API 端点,自动分页枚举。

---

## 8. AI 分析

### 8.1 统一的 AI 调用契约

所有 AI 分析通过统一的接口调用(由 spec 08 定义):传入渲染后的 prompt 字符串,返回结构化的分析结果(含 `summary` 和 `detail` 字段)。

**prompt 构造规则**:prompt 由 Jinja 模板渲染,业务数据(diff 文本、release 数据、README 内容等)直接嵌入模板。模型输出经结构化解析(含 `json_repair` 兜底)。

**等价性判定标准**:AI 调用契约的等价性以**模型输入的 token 序列**为准——即合并后的最终文本(指令 + 数据)与旧实现可证明等价。不要求 Python API 签名一致。

**为什么不再有 content/stdin 分离**:旧架构因命令行子进程的参数长度限制,把"指令"(prompt)和"数据"(content)分离,数据通过 stdin 传入。新架构通过 API 调用,请求体无长度限制(`max_diff_length` 已是保护机制),因此所有业务数据直接嵌入 prompt 模板。模板中所有"via stdin"措辞必须更新为符合 API 调用方式的表述(如"以下是待分析的 diff 内容")。

### 8.2 三种分析

| 分析类型 | 业务目标 | prompt 模板 | 输入数据 |
|---|---|---|---|
| commit diff 分析 | 分析代码变更摘要和详情 | `analysis_prompt.j2` | diff 文本 + commit message 列表 |
| release 分析 | 分析 release 内容和变更 | `release_analysis_prompt.j2` | release 数据(tag、标题、notes、发布时间、commit hash、diff 内容) |
| README 分析 | 分析新发现仓库的用途 | `readme_analysis_prompt.j2` | 仓库名、描述、README 内容 |

### 8.3 截断规则

| 分析类型 | 截断 | 阈值 |
|---|---|---|
| commit diff | 截断 diff 文本 | `max_diff_length`(默认 100_000) |
| release | 截断 release diff 内容 | 同上 |
| README | **无截断**(异常上抛由调用方处理) | — |

### 8.4 失败降级

| 分析类型 | 失败处理 |
|---|---|
| commit diff | 内部捕获 → fallback summary/detail,返回 |
| release | 异常上抛给 `analyze_all_releases` → 该 release 用 fallback,其他 release 继续 |
| README | 异常上抛给 `process_new_repo` → fallback,仓库仍上报 |

### 8.5 JSON 解析契约

期望 AI 输出严格 JSON `{"summary": str, "detail": str}`。解析顺序:
1. 贪心正则匹配首个 `{` 到末个 `}`。
2. `json.loads`。
3. 失败 → `json_repair` 修复后重试;非 dict → 抛异常。
4. `summary`/`detail` 任一为空 → 抛异常。

---

## 9. 报告生成与落库

### 9.1 单仓库报告(`RepositoryReport`)

每个仓库的检查结果承载为结构化的 `RepositoryReport` 数据,塞入 `ReportSection.payload`:

| 字段 | 业务含义 |
|---|---|
| `repo_name` | `owner/repo` |
| `repo_web_url` | GitHub URL |
| `branch` | 分支 |
| `commit_count` | 本次 diff 的 commit 数(无 diff 时 0) |
| `current_commit` | 当前 HEAD |
| `previous_commit` | 上次 HEAD(首次为 None) |
| `commit_messages` | commit message 列表 |
| `analysis_summary` | AI 摘要(失败时为 fallback) |
| `analysis_detail` | AI 详情(失败时为空) |
| `truncated` | diff 是否被截断 |
| `original_diff_length` / `analyzed_diff_length` | 截断前后的长度 |
| `releases` | release 分析结果列表(每项含 `ai_summary`/`ai_detail`),无 release 时为 None |

### 9.2 单仓库报告模板(`repo_report.j2`)

**报告结构**:
- 二级标题:仓库名(含指向 GitHub 的链接)+ 分支与 commit 数小标签。
- **release 块**(仅当有 release):每个 release 用折叠块展示标题、tag、notes、AI 分析摘要(或 fallback)、详情折叠块。
- **分隔符**(仅当同时有 release 和 commit)。
- **commit 块**(仅当有 commit):可选的截断警告 + 每条 commit message(多行用折叠块、单行用 div)+ AI 分析摘要(或 fallback)+ 详情折叠块。

**HTML 转义规则(安全关键)**:
- commit message 内容**必须** HTML 转义(防 XSS——commit message 来自外部)。
- AI summary/detail**不**转义(受信输出,可能含格式化 HTML)。

**分隔符规则**:
- release 块和 commit 块之间有且仅有一个 `---`(当两者都存在时)。
- 只有 release(无 commit)→ 无 `---`。
- 只有 commit(无 release)→ 无 `---`。
- 绝不出现连续两个 `---`。

**空字段隐藏规则**:
- AI 分析摘要为空 → 显示 fallback 文案。
- AI 分析详情为空 → 隐藏"查看详细分析"的折叠块。

### 9.3 聚合报告落库(简化决策)

**简化**:repo integration 从原"聚合 + 每 repo 双落库"简化为**只落库 1 条聚合报告**。

- 所有 repo 的 `RepositoryReport` 经 reports pipeline 聚合渲染,落库为一条 `report_type="repo_update"` 的 Report 行。
- `commit_count` = 全部 repo 的 commit 总数。
- 不再为每个 repo 单独落库 `Report(repo_id=...)` 行。
- Web UI 通过 `GET /api/v1/reports?report_type=repo_update` 查询聚合报告。

### 9.4 聚合报告模板(`aggregated_report.j2`,核心持有)

pipeline 把所有 repo 的 section 聚合:
- section 之间用 `---` 连接。
- 含状态摘要行(✅ N  ❌ N  ➖ N,emoji+数字间一个空格,数字到下个 emoji 间**两个空格**)+ ` — ` + i18n 文本。
- 状态摘要展开为每 repo 的 `{icon} {repo_name}` 列表(icon 来自 `status_icon` macro:success=✅/failed=❌/其他=➖)。
- batch 提示:`total_batches > 1 and batch_index < total_batches - 1` 时显示斜体 `More reports will follow in the next batch...`。
- 生成时间戳与 footer(footer macro 来自 `report_base.j2`)。

### 9.5 batch 切分与按 batch 派发通知

聚合报告按 `markpost.max_batch_size` 切分成多个 batch上传,**每个 batch 派发一次 `ReportEvent`**(详见 spec 09)。通知 title 固定为 `_("Progress Report for Open Source Projects")`(**不是** AI 生成的 unified_title);通知 summary 是 `_("This report covered {count} projects with {commits} commits total").format(...)`。

### 9.6 发现仓库的报告与通知

DiscoveredRepoEvent 聚合后:
- 落库为一条 `report_type="repo_new"` 的报告(commit_count = 发现仓库数,title 由 AI 生成,fallback `"Progress Report for Open Source Projects - {date}"`)。
- 渲染模板 `discovered_repositories_report.j2`(位于核心,因为 discovered 报告不归属单一 integration 的 reports 通道,而是作为通知事件 + 单独落库)。
- 排序:按 `created_at` 降序。
- 每个仓库:标题(含链接)、创建时间、描述(引用块)、README 分析摘要、可选的详情折叠块。
- 仓库间用 `---` 分隔。
- 空情况:`_No repositories discovered._`。

### 9.7 unified summary 前置注入

聚合报告的 AI 生成的 summary **前置**到报告 content:
```
full_content = f"{summary.strip()}\n\n{aggregated_report}" if summary.strip() else aggregated_report
```
失败 fallback:summary=""(不前置)。此 `full_content` 落库为 Report.content。

---

## 10. 通知事件

### 10.1 仓库更新事件(`ReportEvent`)

每个 batch 的聚合报告经 pipeline 处理后构造一个 `ReportEvent`,加入 `RunResult.events`。integration **不需要手动构造** ReportEvent——pipeline 自动处理。

`ReportEvent` 携带:title(固定)、summary(固定拼接)、batch 信息、markpost_url。

### 10.2 发现仓库事件(`DiscoveredRepoEvent`)

当 owner 发现新仓库时,integration **必须**构造 `DiscoveredRepoEvent` 并加入 `RunResult.events`。

`DiscoveredRepoEvent` 字段(定义在 `cli/notifications/events.py`):

| 字段 | 业务含义 |
|---|---|
| `owner` | owner 名称 |
| `name` | 仓库名(优先用 `name_with_owner` 如 `alice/repo`) |
| `url` | 仓库 URL |
| `description` | 仓库描述 |

> README 分析结果(`readme_summary`/`readme_detail`)需要通过事件的扩展字段或附加数据承载。如果 `DiscoveredRepoEvent` 当前结构不足以容纳,需要扩展该数据类(由 spec 10 决定)。

### 10.3 通知模板与格式

#### repo_update(ReportEvent)

通知模板 `cli/notifications/templates/report/{plain_text, html, card_json}.j2`(归属通知系统核心):

| 通道 | 格式 |
|---|---|
| 纯文本(console) | 标题 + 空行 + `{Overview}: {summary}` + 空行 + 统计行(`{Total Repositories}: N` 等,`{Skipped}` 仅当 >0)+ 空行 + markpost URL |
| HTML(email) | 完整 HTML 邮件(蓝色 header、metrics 四宫格、failed/skipped 列表各最多 5 个 + more、action button、footer)——用 `email_notification.j2` 模板 |
| 卡片 JSON(feishu) | overview div + `<hr>` + stats div(4 field)+ 可选 failed/skipped repos div + 可选 action button |

**title 的 batch 后缀**:`total_batches > 1` 时追加 ` ({batch_index+1}/{total_batches})`。

#### discovered_repo(DiscoveredRepoEvent)

通知模板 `templates/notifications/discovered_repo/{plain_text, html, card_json}.j2`:

| 通道 | 格式 |
|---|---|
| 纯文本(console) | 标题 + 空行 + 每仓库 `{name} - {url}`(**无** `•` 前缀,最多 5 个)+ `... and {N} more`(若 >5)+ 空行 + markpost URL |
| HTML(email) | `<h2>{escaped title}</h2><ul>` 每仓库 `<li><a href="{url}">{name}</a></li>`(最多 5 个)+ `<li>... and {N} more</li>`(若 >5)+ 可选 markpost 链接 |
| 卡片 JSON(feishu) | 每仓库 `div` 含 `[{name}]({url})`(**无** `•`,最多 5 个)+ `<hr>` + `... and {N} more`(若 >5)+ `<hr>` + `_Generated by Progress_`。`card_link` = markpost URL |

### 10.4 通道配置边界

- **通道配置**(`[[notification.channels]]`)由 spec 02/10 定义,核心统一管理。
- **integration 不关心通道**:只产出事件,不关心发到哪些通道、通道连接参数等。
- 详见 spec 10。

---

## 11. 边界行为与 edge cases

### Commit 跟踪
| 场景 | 期望行为 |
|---|---|
| 空仓库(0 commit) | 首次检查返回 None;若无 release → 跳过该仓库 |
| 无新 commit(HEAD 未变) | 返回 None;若也无 release → 跳过 |
| 首次检查 total=1, lookback=3 | recent 策略,commit_count=1 |
| 首次检查 total=10, lookback=3 | range 策略,commit_count=3 |
| 首次检查 total=2/3, lookback=3 | recent 策略(total ≤ effective_lookback) |
| diff 为空字符串(strip 后) | 不推进 commit checkpoint,跳过 commit 分析 |
| clone 失败 | 重试 3 次(指数退避 3s/6s),最终失败 → 该仓库失败 |
| git lock 文件冲突 | fetch+reset 内部清理 `.git/*.lock` 后重试 |
| commit message 含 HTML 标签 | 模板 HTML 转义(防 XSS) |
| 多行 commit message | 折叠块(summary=首行,body=剩余) |
| 单行 commit message | div |
| AI 超时/异常 | fallback summary/detail,不阻塞 |
| AI 返回畸形 JSON | json_repair 修复;仍失败 → 异常 → fallback |

### Release 跟踪
| 场景 | 期望行为 |
|---|---|
| 仓库无 release | 返回空列表 → release 块跳过 |
| 首次 release 检查 | 只上报最新的 1 个 release |
| 增量检查 | 上报所有 `published_at > checkpoint` 的 release(严格大于) |
| release 的 `published_at` 不可解析 | 该 release 被跳过 |
| checkpoint 时间戳是字符串 | 解析;失败置 None |
| checkpoint 时间戳是 naive datetime | 强制加 UTC |
| release notes 为 None | 用空字符串 |
| release notes 超大 | 无显式截断(仅 diff 内容截断) |
| release diff 超过阈值 | 截断,标记 truncated |
| release commit 查询失败 | commit hash 为 None,不阻塞 |
| release 分析 AI 失败 | 该 release 用 fallback,其他 release 继续 |
| release 分析整体异常 | 记错误,继续到 commit 分析(不阻塞) |

### Owner 发现
| 场景 | 期望行为 |
|---|---|
| 首次发现(水位为 None) | 只上报最新的 1 个仓库 |
| 增量发现 | 上报所有 `created_at > 水位` 的仓库(严格大于) |
| owner 0 仓库 | 返回空,仍盖戳 |
| owner 名下仓库众多 | 自动分页枚举全部(无硬上限) |
| fork 仓库 | 过滤掉 |
| 仓库已在 Repository 表中 | 跳过(去重,已接受的改进) |
| 仓库无 README 或 README 拉取失败 | 跳过(不上报) |
| README 超过 50_000 字符 | 截断 |
| README 404 | has_readme=False,不记 warning,跳过 |
| owner 发现异常 | 记错误,返回空,不阻塞其他 owner |
| README 分析 AI 失败 | fallback,仓库仍上报 |

### 配置/状态
| 场景 | 期望行为 |
|---|---|
| 无 token | 配置同步仍跑;release 跟踪和 owner 发现跳过;commit 跟踪仍跑(本地 git) |
| 无效 URL | 配置加载时校验拒绝;简写 `owner/repo` 通过校验进入 clone |
| 私有仓库 404 | API 调用抛异常 → 各路径捕获 |
| Rate limit | tenacity 重试,最终失败上抛 |
| proxy 配置 | 共享 ClientSession 统一持有 proxy |
| repo 从 config 移除 | GC 删除 Repository 行(checkpoint 丢失) |
| owner 从 config 移除 | GC 删除 GitHubOwner 行 |
| disabled repo/owner | 保留在表中,run 跳过 |
| 手动重置 commit checkpoint | release checkpoint 不受影响(独立) |
| 手动重置 release checkpoint | commit checkpoint 不受影响(独立) |
| PUT /config/repo 修改后 | DB config 表更新,Repository 表不变,下次 run 时 sync |

---

## 12. 并发、超时、重试

| 项 | 值 |
|---|---|
| git 操作超时 | `cfg.github.git_timeout`(默认 300s) |
| clone 重试 | 3 次(指数退避 3s/6s) |
| git 命令重试 | 3 次(2s/4s 指数),lock 错误时清理后重试 |
| AI 超时 | `cfg.analysis.timeout`(默认 600s) |
| AI 重试 | `cfg.analysis.retries`(默认 3),`retry_delay`(默认 5s,倍增封顶 60s) |
| AI 全局并发 | `AI_CONCURRENCY=1`(全局信号量,序列化所有 AI 调用) |
| GitHub API 重试 | tenacity 重试 5xx/RateLimit;4xx/404 不重试 |
| 仓库检查并发 | `run(concurrency=...)`,默认 1;>1 时用信号量;每任务传播父 OTel context |
| owner 发现并发 | **串行**(不并发) |
| 单仓库内 release 分析 | 串行(逐个 release) |

---

## 13. 测试矩阵(验收清单)

### 数据模型与 sync
- [ ] Repository 全字段建模(含 3 个 release checkpoint 字段),migration 一致
- [ ] GitHubOwner 全字段建模,`unique_together=(owner_type, name)`
- [ ] 所有 nullable 字段的 None 语义正确
- [ ] `sync` repos:upsert(URL 规范化)+ GC(基于 URL 集合,含 disabled)
- [ ] `sync` owners:upsert(仅更新 enabled)+ GC(基于 type+name key)
- [ ] URL 规范化:`owner/repo` → `https://github.com/owner/repo.git`
- [ ] sync 只在 run 时触发,PUT /config 不触发

### Commit 跟踪
- [ ] 空仓库 → 跳过
- [ ] 无新 commit → 跳过(若也无 release)
- [ ] 首次检查 4 种情况:total=1/2/3(recent)、total=10(range)
- [ ] 增量检查
- [ ] diff 为空字符串 → 不推进 checkpoint
- [ ] clone 重试 3 次
- [ ] git lock 自愈

### Release 跟踪
- [ ] 无 release → 跳过
- [ ] 首次检查只上报最新 1 个
- [ ] 增量检查(严格大于)
- [ ] published_at 多格式(Z/+00:00/空格分隔)
- [ ] checkpoint 时间戳是字符串/naive datetime 的处理
- [ ] release notes None → 空字符串
- [ ] release diff 截断
- [ ] release commit 查询失败 → commit hash=None
- [ ] release 分析 AI 失败 → fallback
- [ ] release 与 commit checkpoint 独立推进
- [ ] release 分析异常不阻塞 commit
- [ ] 手动重置一个 checkpoint 不影响另一个

### Owner 发现
- [ ] 首次发现只上报最新 1 个
- [ ] 增量发现(严格大于)
- [ ] 0 仓库 → 空但仍盖戳
- [ ] fork 过滤
- [ ] 仓库已在 Repository 表 → 跳过(去重)
- [ ] README 截断(50_000)
- [ ] README 404 → 跳过不记 warning
- [ ] README 拉取失败 → 跳过
- [ ] discovered repo 不入 Repository 表
- [ ] owner 异常不阻塞其他 owner

### AI 分析
- [ ] 统一接口(prompt 嵌入业务数据,无 stdin/content 分离)
- [ ] commit diff 截断 + fallback
- [ ] release 截断(在 prompt 渲染前)
- [ ] README 无截断(异常上抛)
- [ ] JSON 解析:正常/畸形修复/空/缺字段

### 报告与通知
- [ ] 单仓库报告:release-only/commit-only/混合
- [ ] commit HTML 转义,AI HTML 不转义
- [ ] 分隔符规则(无连续 `---`,无尾分隔)
- [ ] 空分析字段隐藏详情链接
- [ ] 聚合报告只落库 1 条(简化,不每 repo 落库)
- [ ] unified summary 前置注入到 content
- [ ] batch 切分 + 按 batch 派发 ReportEvent
- [ ] oversize stub 机制(WebUI 链接)
- [ ] DiscoveredRepoEvent 实际被发射
- [ ] repo_update 通知:3 通道格式(console/email 复杂 HTML/feishu 卡片)
- [ ] discovered_repo 通知:3 通道格式(最多 5 个 + more)
- [ ] title batch 后缀

### 并发与错误
- [ ] 仓库检查并发参数可调(默认 1 串行;>1 信号量)
- [ ] OTel context 传播
- [ ] owner 发现串行
- [ ] zero-config(无 token)
- [ ] 错误聚合:单失败 → partial;全失败 → failed
