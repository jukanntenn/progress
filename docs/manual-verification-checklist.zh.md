# 手工验证清单

[English](manual-verification-checklist.md) | 中文

由人工执行对 Progress 的验证，覆盖**配置重构**与**核心业务逻辑**（仓库跟踪、分析、报告、通知、提案/changelog 跟踪、所有者监控）。

每个步骤列出**动作**、**预期**与**验证**。需要联网、AI（人工智能）或外部服务的步骤均已标注。首次执行时按顺序运行；后续各部分依赖 A 部分播种的配置。

## 0. 前置条件

- 已安装 `uv`（Python）与 `pnpm`（前端），并已运行 `uv sync` 与 `cd web && pnpm install`。
- **带 AI 分析的仓库跟踪**：设置 `[analysis]` 的 `model` + `api_key`（经 API 的 Pydantic AI，如 `anthropic:claude-sonnet-4`），**或者**留空 `api_key` 做无 AI 冒烟测试（报告内容是截断的 diff，除 AI 调用外仍会走完整条流水线）。
- **所有者/提案/changelog 跟踪**：需要到 GitHub 的出站网络。
- 可选外部服务：飞书 webhook / SMTP 服务器（仅相应的通知步骤需要；`console` 渠道什么都不需要）。

## 1. 环境搭建（隔离）

使用一次性数据库，保证真实的 `data/progress.db` 永不被触碰。

```bash
# 1.1 copy the seed file
cp config.example.toml config.toml
#     -> set data_dir to an absolute scratch dir, e.g. /tmp/progress-verify
#     -> set [github] gh_token (any non-empty value works for cloning public repos;
#        a real PAT is needed for private repos / higher rate limits)
#     -> leave [analysis] api_key empty for the no-AI smoke path (diff truncation)
#     -> keep 1 small public repo under [[repos]] (e.g. "octocat/Hello-World")

# 1.2 start backend (port 8000 = the frontend's default proxy target)
PYTHONPATH=src CONFIG_FILE=config.toml uv run fastapi dev --port 8000

# 1.3 in another shell, start frontend
cd web && pnpm dev          # http://localhost:5173
```

**验证：**后端日志打出 `Application startup complete`；打开 `http://localhost:5173/` 能无错加载报告页。

> 提示：测试中途要彻底重置，删除临时的 `data_dir` 并重启后端；首次运行会从 `config.toml` 重新播种。

---

## A 部分：配置

本节动手验证配置模型（数据库是唯一真源；TOML 文件是一次性种子，缘由见[配置 PRFC](../.agents/rfcs/implemented/architecture/2026-06-26-config-database-single-source.zh.md)），并补充**所有者编辑修复**的验证。

### A1. 首次运行时文件为数据库播种
- **动作：**以全新的临时数据库启动后端（1.2）。
- **预期：**数据库 blob 与 `repositories`/`github_owners` 表由 `config.toml` 填充。
- **验证（数据库）：**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT version, json_extract(data,'$.analysis.provider') FROM app_config;"
  sqlite3 <data_dir>/progress.db "SELECT name, branch, enabled FROM repositories;"
  sqlite3 <data_dir>/progress.db "SELECT owner_type, name, enabled FROM github_owners;"
  ```
  数值与 `config.toml` 一致；`app_config.version = 1`。
- **验证（UI）：**`http://localhost:5173/config` 显示这些值和 "Stored in the database (version 1)"。

### A2. Web 编辑持久化且不触碰文件
- **动作：**在 Configuration 页面修改一个标量（如 `Analysis → timeout`），点击 **Save**。
- **预期：**toast（轻提示）为 "Configuration saved"；页面显示 `version 2`；数据库中的值已变更；`config.toml` 不变。
- **验证：**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT version, json_extract(data,'$.analysis.timeout') FROM app_config;"
  grep "timeout" config.toml        # still the original value
  ```

### A3. 通过 Web UI 增/改/删所有者 *（近期修复）*
- **动作：**在 Configuration 页面 → Owners 部分：点击 **Add Owner**，设置类型 + 名称，点击 Owners 的 **Save**。
- **预期：**toast 为 "Owners saved"（而非 "Save failed"）；`version` 不变（所有者是独立表）；新所有者出现在数据库中。
- **验证：**
  ```bash
  sqlite3 <data_dir>/progress.db "SELECT owner_type, name, enabled FROM github_owners;"
  curl -s http://127.0.0.1:8000/api/v1/config/owners | python3 -m json.tool
  ```
- **另请尝试：**把 `enabled` 关掉再 Save → 行保留、`enabled=0`（替换会保留已禁用的所有者而不是删除）。移除一行再 Save → 行被清理。
- **失败信号：**出现 422 / "Save failed" toast 意味着 `type`/`owner_type` 回归复现。

### A4. 通过 Web UI 增/改/删仓库
- **动作：**Repositories 部分 → **Add Repository** → 输入 URL → Save。
- **预期：**"Repositories saved"；新仓库进入 `repositories` 表；既有行保留其 `id` 与运行时状态。
- **验证：**`sqlite3 <data_dir>/progress.db "SELECT id,name,url,enabled FROM repositories;"`

### A5. 机密脱敏与往返
- **动作：**把 `GitHub → gh token` 设为新值并 Save；再修改另一个字段，*不重新输入令牌*直接 Save。
- **预期：**GET 始终显示 `********`；数据库存真实值；第二次保存将其保留。
- **验证：**`GET /api/v1/config` 显示 `"gh_token": "********"`，而 `sqlite3 ... "SELECT json_extract(data,'$.github.gh_token') FROM app_config;"` 两次都持有真实令牌。

### A6. 播种后文件被忽略（核心保证）
- **动作：**直接在 `config.toml` 里编辑一个应用配置值（如 `analysis.timeout = 999`），再重启后端（1.2）。
- **预期：**`GET /api/v1/config` 仍返回**数据库**值而非 999。
- **验证：**
  ```bash
  curl -s http://127.0.0.1:8000/api/v1/config | python3 -m json.tool
  ```
- **恢复路径：**编辑 `config.db.toml` 并重启后端；每次启动都会重新导入种子文件（优先级 `DB > seed > defaults`，种子只填充数据库尚无的键），之后数据库反映该文件且 `version` 递增。

---

## B 部分：核心业务逻辑

### B1. 仓库跟踪：首次运行 `*(network; AI optional)*`
- **动作：**`uv run progress -c config.toml check`
- **预期：**每个启用的仓库克隆进 `workspace_dir`；分析最初 `analysis.first_run_lookback_commits` 个提交；每个仓库生成一份报告；记录该仓库的 `last_commit_hash`。
- **验证（数据库）：**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT name, last_commit_hash IS NOT NULL AS has_checkpoint, last_check_time FROM repositories;"
  sqlite3 <data_dir>/progress.db \
    "SELECT id, repo_id, title, commit_count, created_at FROM reports ORDER BY id DESC LIMIT 5;"
  ```
- **验证（文件系统）：**`ls <workspace_dir>` 能看到克隆出的仓库。
- **验证（UI）：**`http://localhost:5173/` 列出**聚合**报告（列表显示不归属单一仓库的报告）；点进 `/report/<id>` 渲染分析（用真实 provider 时是 AI 摘要；`truncate` 时是截断 diff）。单仓库报告带 `repo_id`，可按 id 查看但不在列表中。

### B2. 幂等重跑（无新提交）
- **动作：**立即再次运行 `check`。
- **预期：**无新报告（`last_commit_hash` 之后没有新内容）；无重复报告。`reports` 行数不变。
- **验证：**对比运行前后的 `reports` 行数 / 最大 `id`。

### B3. 新提交检测 `*(network; AI optional)*`
- **动作：**不等上游，强制重新分析一个已知提交：
  ```bash
  sqlite3 <data_dir>/progress.db \
    "UPDATE repositories SET last_commit_hash = '<older-or-null-sha>' WHERE name='<the repo>';"
  uv run progress -c config.toml check
  ```
  （或等真实的上游提交出现后再运行。）
- **预期：**新报告覆盖自记录的检查点以来的提交；`last_commit_hash` 前进。
- **验证：**`reports` 中出现该仓库的新行；UI 显示它。

### B4. 所有者监控 `*(network)*`
- **前置条件：**经 UI 添加一个账号近期有公开仓库的活跃所有者（A3）；确保存在通知渠道（B7 的 console）。
- **动作：**`uv run progress -c config.toml check`
- **预期：**该所有者新建的仓库被发现并呈现（报告 + 通知）。按设计，发现的仓库是**临时的**：会进报告/通知，但**不**加入 `repositories` 表。
- **验证：**控制台输出 / 日志含该所有者的发现仓库条目；`repositories` 表不变（不自动晋升）。

### B5. 提案跟踪 `*(network)*`
- **前置条件：**在配置 blob（UI → Proposal Trackers）里启用一个或多个种类，如 `proposal_trackers = ["pep"]`。运行：`uv run progress -c config.toml track-proposals`（或 `check`）。
- **预期：**跟踪器仓库被克隆；提案被解析；新增 / 状态变化（接受/拒绝/撤回）的提案触发通知。
- **验证：**跟踪器表已填充；第二次运行无变化时无新提案事件。`--trackers-only` 跳过仓库跟踪：`uv run progress -c config.toml check --trackers-only`。

### B6. Changelog 跟踪 `*(network)*`
- **前置条件：**经 UI 添加一条 `[[changelog_trackers]]` 条目（如某个 CHANGELOG.md 的 raw URL、解析器 `markdown_heading`）。
- **动作：**`uv run progress -c config.toml check`
- **预期：**从 changelog 解析出当前版本；之后某次运行遇到更新的版本时，产出合并的发布报告 + 通知。
- **验证：**`changelog_tracker` 相关的行/通知反映解析出的版本；版本无变化时重跑不产生新内容。

### B7. 通知
- **控制台（无外部依赖）：**设置 `console` 通知渠道（UI → Notification），带着触发事件（新提交 / 提案 / 发布）运行 `check`。**预期：**通知消息打印到 stdout / 日志。
- **飞书 `*(external)*`：**添加带真实 webhook URL 的飞书渠道；触发一个事件。**预期：**消息落进飞书群。
- **邮件 `*(external)*`：**添加凭据有效的 SMTP 邮件渠道；触发一个事件。**预期：**邮件到达收件人。
- **验证机密脱敏：**飞书的 `webhook_url` 与邮件的 `password` 在 `GET /api/v1/config` 中显示为 `********`，但发送时照常工作。

### B8. 报告与 RSS
- **UI：**`http://localhost:5173/` 分页报告列表；打开一份报告 → 完整内容在 `/report/<id>`。
- **API：**
  ```bash
  curl -s "http://127.0.0.1:8000/api/v1/reports?page=1" | python3 -m json.tool
  curl -s http://127.0.0.1:8000/api/v1/reports/<id> | python3 -m json.tool
  ```
  列表返回聚合/全局报告（`repo_id` 为 null：仓库更新汇总、提案、changelog、所有者发现）；页大小由服务端固定（10）。任何报告（含单仓库报告）都可经详情端点按 id 获取。
- **RSS：**`curl -s http://127.0.0.1:8000/api/v1/rss | head` → 列出近期报告的有效 RSS XML。在阅读器里订阅以确认。

---

## C 部分：边界情况与健壮性

- **C1. 无效仓库 URL：**经 API 添加 `url = "not-a-url"` 的仓库 → `PUT /api/v1/config/repos` 返回 **422**；UI 显示校验错误。
- **C2. 不存在的仓库：**播种一个 GitHub 上不存在的仓库，运行 `check`。**预期：**被优雅处理（跳过/记日志），不崩溃、无报告。
- **C3. 空配置（无仓库/所有者）：**在新播种且没有仓库的数据库上运行 `check`。**预期：**干净完成，无报告。
- **C4. 乐观锁冲突：**在两个标签页打开配置页，标签页 1 编辑并保存，再在标签页 2 保存。**预期：**标签页 2 收到 409 / "modified elsewhere" toast 并刷新。（可经 API 复现：带过期 `version` 发 `POST /api/v1/config`。）
- **C5. 校验拒绝：**以无效数据（如缺少 `[github]`）发 `POST /api/v1/config` → **400**，错误信息可读。
- **C6. 重启保全一切：**多次编辑后重启后端：数据库里的全部配置与报告完好；没有任何内容被重新播种/覆盖。

---

## D 部分：清理

```bash
# stop servers (Ctrl+C in each shell), then:
rm -rf <data_dir>          # scratch DB, cloned repos, logs
rm -f config.toml          # throwaway seed (config.example.toml is untouched)
```

只要 `data_dir` 指向临时目录，你真实的 `data/progress.db` 与任何生产配置都不受影响。

---

## 通过/失败汇总

| 领域 | 步骤 | 关键通过信号 |
|---|---|---|
| 配置：播种 | A1 | 数据库与文件一致，`version=1` |
| 配置：Web 编辑 | A2、A4、A5 | 数据库变更、文件不变、机密已脱敏 |
| 配置：所有者修复 | A3 | 所有者保存成功（无 422） |
| 配置：文件被忽略 | A6 | 数据库值在文件编辑 + 重启后保持 |
| 仓库跟踪 | B1–B3 | 生成报告；重跑无新产出；新提交 → 新报告 |
| 所有者监控 | B4 | 发现的仓库被呈现、不自动加入 |
| 提案跟踪 | B5 | 提案被解析；变化有通知 |
| Changelog 跟踪 | B6 | 检出版本；新发布有报告 |
| 通知 | B7 | 控制台恒有；配置了 feishu/email 后才有 |
| 报告与 RSS | B8 | UI + API + RSS 都返回内容 |
| 健壮性 | C1–C6 | 错误被处理、不崩溃、不静默覆写 |

观察结果与**预期**不符即该步骤**失败**；记录命令输出 / 截图与数据库状态以供排查。
