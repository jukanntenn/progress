# 配置

[English](config.md) | 中文

Progress 采用**双文件配置模型**（spec 02），把基础设施配置（由 Ansible / 部署者持有）与面向用户的配置（由 Web UI / 数据库持有）物理分离。两类配置永不重叠，因此一次部署不会覆盖用户的修改，反之亦然。

## 配置如何拆分

| 类别 | 归属 | 存储 | 挂载 | 内容 |
|---|---|---|---|---|
| **Ansible** | 部署者 | `config.toml` | 只读文件 | 仅 `state_home` |
| **核心 Web** | Web UI / 用户 | 数据库 `config` 表（`section="core"`） | 数据库（可写） | language、timezone、github、analysis、markpost、notification、observability、web、schedule |
| **插件** | Web UI / 用户 | 数据库 `config` 表（`section=<plugin>`） | 数据库（可写） | 各集成的配置（`repo`、`changelog`、`proposal`） |

`state_home` 是唯一的基础设施键：所有运行时数据（数据库、日志、克隆的仓库、可观测性导出）的根目录，其余一切路径都由它派生。

## 两个文件

### `config.toml`（Ansible 类）

**仅**承载 `state_home`。在 Docker 中以只读方式挂载。

```toml
state_home = "data"
```

环境变量覆盖：`PROGRESS_STATE_HOME`。

### `config.db.toml`（数据库种子，Web 类）

**种子文件**与 `config` 表的布局互为镜像：每个顶层表对应一条 `section` 记录。把它放在 `config.toml` 旁边；启动时会将其导入数据库（见[种子导入](#seed-import)）。

```toml
[core]
language = "en"
timezone = "UTC"

[core.github]
gh_token = ""                       # SecretStr; empty → GitHub tracking disabled + warning
proxy = ""                          # HTTP proxy for GitHub + git; v2ex opts in (e.g. "http://127.0.0.1:7890")

[core.analysis]
provider = ""                       # e.g. "anthropic"; empty → AI disabled (truncation fallback)
model = ""                          # e.g. "claude-sonnet-4"
api_key = ""                        # SecretStr
base_url = ""                       # custom endpoint for OpenAI-compatible services; empty → provider default
language = "en"

[core.markpost]
enabled = false
url = ""                            # SecretStr; format: https://host/post_key (e.g. https://markpost.cc/mpk-abc123)
max_batch_size = 1048576

[[core.notification.channels]]
type = "console"
enabled = true

[[core.notification.channels]]
type = "email"
enabled = false
host = "smtp.example.com"
port = 465
user = "sender@example.com"
password = ""                       # SecretStr
from_addr = "progress@example.com"
recipient = ["alice@example.com"]
starttls = false
ssl = true

[[core.notification.channels]]
type = "feishu"
enabled = false
webhook_url = ""                    # SecretStr

[core.observability.bugsink]
dsn = ""                            # SecretStr; empty → error capture disabled
environment = "production"

[core.web]
base_url = ""                       # public base URL for report back-links
```

复制 `config.example.db.toml` 作为起点。

<a id="seed-import"></a>

## 种子导入

只要 `config.db.toml` 与 `config.toml` 同处一个目录，每次启动都会把它重新导入数据库 `config` 表：

- **优先级**：`DB > seed > code defaults`。种子只填充数据库里尚不存在的键，因此 Web UI 上的修改在重启后依然保留。
- **全部 section** 都会导入：`[core]` 加上各插件 section（`[repo]`、`[changelog]`、`[proposal]`），每个集成都从数据库读取自己的配置。
- **校验**：`[core]` 直接透传；插件 section 按各自注册的 Pydantic schema 校验，校验失败的 section 会被记录日志并跳过。
- **生产环境**：运维者必须确保 `config.db.toml` **不**存在（数据库是唯一真源；`.gitignore` 已排除该文件）。修改配置请走 Web UI 或 `PUT /api/v1/config/{section}`。
- **测试 / 首次部署**：放置 `config.db.toml`，不碰 Web UI 即可种下初始配置。

## 编辑配置

- **Web UI**：*配置*页基于 JSON Schema（`GET /api/v1/config/schema`）渲染 RJSF 表单，并经 `PUT /api/v1/config/{section}` 写入。
- **API**：`GET /api/v1/config` 以**明文**返回所有 section（机密字段携带真实值；Web UI 用 `type="password"` 输入框做了掩码）；`PUT /api/v1/config/{section}` 用该 section 的 Pydantic 模型（`extra="forbid"`）校验载荷，并写入规范化后的明文副本。校验失败返回 422，数据库保持原样。
- **种子文件**：编辑 `config.db.toml` 后重启（重新导入数据库）。

机密（`gh_token`、`api_key`、`password`、`webhook_url`、`dsn`、markpost 的 `url`）都是 `pydantic.SecretStr`：以真实明文存入数据库（受信任的内部存储），并由 API 原样返回。浏览器把它们渲染为密码输入框（带显示切换）；不存在掩码哨兵值：你提交什么，就存储什么。

系统内部字段（`state_home`、`auth.secret_key`、`auth.initial_admin_password`）不出现在可编辑 schema 中，也不出现在 API 响应中；写入时始终保留其数据库值。

## 调度

`schedule` section 驱动进程内的定时流水线运行（PRFC 2026-08-31）：

```toml
[core.schedule]
cron = "0 6 * * *"   # daily at 06:00 local time; empty disables scheduled runs
```

- cron 表达式由 serve 树上的 `scheduled-run` 行经 `ctx.scheduler`（croniter）求值：使用本地时间；逐条目互斥（上一次运行尚未结束时到来的触发会被跳过并给出警告）；不补跑错过的触发。
- 变更即时生效：通过 API 写入该 section 即可重载调度，无需重启（L0）。
- 容器的 `PROGRESS_SCHEDULE_CRON` 环境变量是 `schedule.cron` 为空时使用的兼容回退；调度在进程内运行。

## 零配置

每个可选功能在缺少前置条件时都会优雅降级，系统绝不会因此启动失败：

- 缺少 `github.gh_token` → GitHub 跟踪（release/owner 发现）禁用 + 警告。
- 缺少 `analysis.provider`/`api_key` → AI（人工智能）分析禁用；报告使用默认标题。
- `markpost.enabled=true` 但 `url` 为空 → MarkPost 发布禁用 + 警告。
- 没有启用的通知渠道 → 跳过分发。

## 优先级

- **Ansible**（`state_home`）：`PROGRESS_STATE_HOME` 环境变量 > `config.toml` > 默认值 `"data"`。
- **Web 类**：`PROGRESS_*` 环境变量（前缀 `PROGRESS_`、分隔符 `__`）在启动时叠加覆盖数据库 + 种子。

## 插件配置

每个集成拥有自己的 `config` 表 section（以 `Integration.name` 为键）。

### `repo`（section `"repo"`）

```toml
[repo]
first_run_lookback_commits = 3      # commits analyzed on a repo's first run
max_reenabled_lookback_commits = 50 # commits analyzed when a repo is stale-reenabled
max_reenabled_lookback_releases = 20 # releases analyzed when a repo is stale-reenabled
reenabled_stale_days = 7            # days without a check before stale reenabled

[[repo.repos]]
url = "vitejs/vite"
branch = "main"
enabled = true
track_commits = true                # enable commit diff tracking
track_releases = true               # enable release tracking

[[repo.owners]]
type = "organization"               # "organization" | "user"
name = "bytedance"
enabled = true
```

当仓库的 `last_check_time` 超过 `reenabled_stale_days` 时，下一次运行改用 `max_reenabled_lookback_commits` / `max_reenabled_lookback_releases` 作为回填窗口，而非常规的增量 diff。把 `track_commits` 或 `track_releases` 设为 `false` 会在不分析的情况下推进相应检查点，从而消除重新启用时的缺口。

### `changelog`（section `"changelog"`）

```toml
[[changelog.trackers]]
name = "Vite"
url = "https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"
parser_type = "markdown_heading"    # "markdown_heading" | "html_chinese_version"
enabled = true
proxy = ""                          # per-tracker HTTP(S) proxy URL; empty → direct fetch
```

- `markdown_heading`：带 `## 1.2.3` 标题的 Markdown。
- `html_chinese_version`：带 `uTools v7.5.1` 这类模式的 HTML。
- `proxy`：仅用于该 tracker 拉取的 HTTP(S) 代理 URL（如 `http://127.0.0.1:7890`，用于不走代理无法访问的 URL，如 `raw.githubusercontent.com`）。留空（默认）→ 直连拉取。与 `core.github.proxy` 相互独立。

### `proposal`（section `"proposal"`）

```toml
[proposal]
trackers = ["eip", "erc", "pep", "rfc", "dep"]
```

| 种类 | 仓库 | 说明 |
|---|---|---|
| `eip` | ethereum/EIPs | 以太坊改进提案 |
| `erc` | ethereum/ercs | 以太坊征求意见稿 |
| `pep` | python/peps | Python 增强提案 |
| `rfc` | rust-lang/rfcs | Rust 征求意见稿 |
| `dep` | django/deps | Django 增强提案 |

### `feed`（section `"feed"`）

Miniflux RSS 阅读器连接。`base_url` 为空 → feed 集成禁用 + 警告（零配置）。见 `specs/integrations/feed.md`。

```toml
[feed]
base_url = "https://miniflux.example.org"   # empty → disabled
api_key = "MF-api-key-xxxx"                  # SecretStr; base_url set but empty → disabled
```

跟踪哪些 feed 由**数据源驱动**（完全取决于 Miniflux 订阅了什么），因此该 section 只承载 Miniflux 凭据，不含 feed 列表。逐 feed 的去重水位线存放在 `feed_trackers` 状态表中，在 `run` 内部推进。
