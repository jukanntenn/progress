# 02 · 配置系统

## 设计目标

配置系统必须满足:

1. **覆盖优先级**:env > 配置来源 > 代码默认值。
2. **零配置**:全部具备最合理默认值,无配置文件也能跑;缺失必要前提(凭据)时功能降级 + 日志提醒,系统不报错。
3. **精简**:代码常量归代码,只动态配置进 Config。
4. **接口通用**:一个 Config 模型 + 合理默认,生产/测试用同一接口,无专用工厂。
5. **两类配置零交集**:Ansible 管理类与 Web 管理类物理隔离,不可能互相覆盖冲突。

## 三类配置(核心架构)

配置按**所有者**分三类,物理隔离存储,零交集:

| 类 | 所有者 | 存储 | 挂载 | 内容 |
|---|---|---|---|---|
| **Ansible 类** | Ansible/部署者 | 文件 `config.toml` | `:ro` 只读 | infra/部署级常量(路径等) |
| **核心 Web 类** | Web UI/用户 | DB `config` 表(section="core") | DB 本就可写 | 用户偏好、凭据、业务调参 |
| **插件配置** | Web UI/用户 | DB `config` 表(section=插件 name) | DB 本就可写 | 各 integration 自定义配置 |

### 决策理由:二分配置消除冲突

第一性原理:**冲突的根本来源是"两个 agent 都能改同一份东西"**。把配置按所有权硬二分(Ansible 类 vs Web 类),两类**零交集**,冲突在结构上不可能发生。无需字段级 ownership 仲裁、无需 mtime 追踪、无需 `managed_by` 元数据。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| 单一配置文件(`config.toml`)管理全部 | Docker 容器挂载必须 `:rw` 才能写,扩大攻击面;且 Web 改的值下次 Ansible 部署会被模板覆盖 |
| DB blob 存全部配置(含 infra) | 反模式:blob/文件漂移、schema 版本迁移、明文 secret、~200 行脱敏补偿代码(当前 `config_store.py` 即此问题) |
| 字段级 `managed_by` + mtime 仲裁 | 过度复杂,edge case 多,不直观;二分配置从结构上消除冲突,无需仲裁 |
| 单文件 + env 触发导入 | 每次依赖 env 变量麻烦;改用约定路径(见下) |

## 根路径统一:`state_home`

所有运行时数据(DB、日志、git 仓库、可观测性导出)的共同根,统一为**一个**配置项 `state_home`,其余路径代码派生,不可配。

### 命名决策

脑暴过 `data_dir`/`base_dir`/`root_dir`/`storage_dir`/`var_dir`/`state_dir`/`state_home`。

**选定 `state_home`**。理由:呼应 XDG `XDG_STATE_HOME` 规范(Linux 桌面/系统服务共识),精准表达"运行时状态/产物的根目录"。`state_dir` 也符合(systemd `StateDirectory=`),但 `state_home` 与 XDG 对齐更贴社区共识。

### 派生规则(代码固定,不可配)

| 派生路径 | 规则 |
|---|---|
| 数据库 | `<state_home>/progress.db` |
| 日志目录 | `<state_home>/logs/` |
| git 仓库 | `<state_home>/repos/` |
| 可观测性导出 | `<state_home>/observability/` |

## 配置文件加载逻辑

```
启动时:
  若未指定配置文件路径 → 使用默认配置(zero config,各功能按前提检查降级)
  若指定了路径但文件不存在 → 报错退出 + 友好提示("config file not found: {path}")
  若指定了路径且存在 → 加载 + pydantic 校验(校验失败→报错退出+友好提示)
```

### 配置来源优先级(pydantic-settings 原生)

`init_settings > env_settings > 文件 > 代码默认值`

pydantic-settings 的 `settings_customise_sources` 返回元组,**先返回的源优先级更高**(基于 `pydantic/_internal/_utils.py:131` `deep_update` 语义)。

## DB 种子约定:`config.db.toml`

为方便测试/首次部署,采用**约定优于配置**:主配置文件同级目录下若有约定命名的种子文件,启动时导入 DB。

### 约定

- 主配置:`<指定路径>/config.toml`(Ansible 类)
- DB 种子:`<指定路径>/config.db.toml`(Web 类:core + 插件配置)

### 加载与合并优先级

```
启动时检测 config.db.toml 是否存在:
  若存在 → 加载为"DB 配置种子"
  加载 DB 中真实存储的配置(config 表)
  合并优先级:DB 真实配置 > 种子文件 > 代码默认值
    (即种子只填补 DB 中缺失的,不覆盖 DB 中已有的)
```

### 生产 vs 测试

- **生产**:运维保证 `config.db.toml` **不存在** → DB 是唯一真相源,Web 编辑生效。`.gitignore` 必须排除此文件。
- **测试/首次部署**:放 `config.db.toml` → 测试者用文件配置,免 Web 操作;每次启动重导(文件即真相)。

### 三层优先级映射

| 场景 | 行为 |
|---|---|
| DB 中某 key 已有值 | 用 DB 的值(Web 编辑生效) |
| DB 中某 key 无值 | 用种子文件的值(测试设的初值) |
| 种子和 DB 都无 | 用代码默认值(zero config) |

## `config` 表 schema

统一存所有 Web 类配置(核心 + 插件),按 section 分区:

| 列 | 类型 | 说明 |
|---|---|---|
| `section` | PK, str | 分区标识:`"core"` 或插件 name(如 `"repo"`) |
| `data` | JSON | 该分区的配置内容(JSON 对象) |
| `updated_at` | datetime | 最后更新时间 |

### 设计要点

- **一行一分区**:`section="core"` 存核心配置;`section="repo"` 存 repo 插件配置。
- **`data` 永远是 JSON 对象**(无论核心还是插件),统一格式。
- **校验用 Pydantic 模型**(`model_validate`):核心定义 core 模型,每个插件定义自己模型,注册到注册表。写入前用对应模型校验(`lax` 模式 + `extra="forbid"`),校验失败抛 `ConfigException`(API 层转 422),**DB 不变**。不用 jsonschema validator——jsonschema 不支持 discriminated union 的 `discriminator` 关键字(OpenAPI 扩展),Pydantic 原生支持且全栈已统一。
- **框架提供统一 API**:`get_config(section)` / `set_config(section, data)` 管理这些配置。
- **前端通过一个接口获取全部配置**(见 12):`GET /api/v1/config` 返回 `{core: {...}, repo: {...}, ...}`;`GET /api/v1/config/schema` 返回合并的 schema。

## 密钥处理:明文往返 + 前端遮蔽(强制)

所有密钥字段**必须**用 Pydantic `SecretStr`,不用裸 `str` + `json_schema_extra` 注解。SecretStr 保证:DB 序列化可控、JSON Schema 自动生成 `format: password`(前端自动密码框)、`model_dump(mode="json")` 自动输出 `**********`(日志/调试安全)。

### 明文往返链(2026-08-10 重构定稿)

| 阶段 | 行为 |
|---|---|
| 配置文件/种子(明文 TOML) | 写真值(如 `gh_token = "ghp_xxx"`) |
| 写入 DB(`set_config`) | Pydantic `model_validate` 校验 → `model_dump(mode="python")` + SecretStr 手动解包 → 存**规范化明文**(coercion 后,如 `"3"` → `3`)。**校验失败绝不落库** |
| `GET /api/v1/config` | 明文返回(secret 为真实值),前端用 `type="password"` 浏览器原生遮蔽 |
| `PUT /api/v1/config` | 前端提交整个表单(formData 明文)→ 后端校验 + dump 明文。提交什么存什么,无 sentinel、无按位置合并 |
| JSON Schema | `SecretStr` 自动生成 `format: password, writeOnly: true`(前端表单自动密码框 + eye 切换显示) |

### 决策理由

- 内网受信环境:明文往返从根本上消除"mask sentinel 字符串巧合匹配"的脆弱性(sentinel 机制曾在 `SecretStr` 接受 `**********` 作为真值时静默损坏配置)。
- 消除整个 sentinel 脱敏补偿层(按数组下标合并 secret、mask 还原、mask 保留),列表删改/重排天然正确——每个 secret 值随其对象整体移动。
- 系统/Ansible 内部字段(`state_home`、`auth.secret_key`、`auth.initial_admin_password`)从可编辑 schema 剥离、GET 返回剥离、写入时始终保留 DB 原值,前端不可见也不可覆盖。
- `SecretStr` 在 `model_dump_json()` 默认输出 `**********`(基于 `pydantic/types.py:1742` `_secret_display`),日志/异常上报天然脱敏;scrub 层(见 04)按字段名 redact 兜底。

### 写入失败契约

- 写入校验失败 → `ConfigException` → API 422 + 结构化错误(`loc: msg` 行,前端可映射到字段)→ **DB 保持原值**(写入未发生)。
- 运行时加载失败(启动 merge / reload)→ 保持 Ansible 默认配置 + 告警,不崩溃。
- `GET /config` 发现 DB 数据损坏 → 422(不部分降级、不返回损坏数据)。

## 配置组织(模块划分)

核心配置聚合在一个文件,各领域配置归各自领域包(Django app 式):

```
src/progress/config/
├── __init__.py        # 公共门面(导出 Config / 加载器 / schema)
├── root.py            # ★ 顶层项目级配置聚合根(CoreConfig)
├── loader.py          # 分层 sources 加载(overrides + base + env)
└── schema.py          # get_config_json_schema()(lru_cache + 合并插件 schema)

# 领域自带 config(呼应 Django app 自带 settings)
src/progress/observability/config.py     # OTel/BugsinkConfig(注:otel 的开关/采样已改代码常量,见下)
src/progress/cli/notifications/config.py # NotificationConfig(discriminated union)
src/progress/integrations/repo/config.py # RepoConfig(插件配置)
src/progress/integrations/changelog/config.py
src/progress/integrations/proposal/config.py
```

### 顶层文件命名决策

脑暴过 `settings.py`/`config.py`/`root.py`/`project.py`/`app.py`/`defaults.py`。

**选定 `root.py`**。理由:`settings.py` 嫌不好(用户反馈);`config.py` 与包名 `config/` 冗余;`root.py` 精准表达"项目级、最顶层、其他领域挂在其下",不冗余、不撞名、短。

### API 自己的配置

API 领域自带配置(若有,如 CORS dev 开关)。但 API 领域配置归 `api/` 包内,**无认证配置**(见 12,无应用层认证)。

## 完整配置清单

### Ansible 类(文件 `config.toml`,`:ro`)

| 项 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `state_home` | str | `"data"` | 运行时数据根路径,DB/log/repos/observability 派生 |

**说明**:Ansible 类只剩这一项。其余原来归 Ansible 的(gh_token/dsn 等)改归 Web 类(用户会改,见 12 无认证说明 + 密钥归属判断)。

### 核心 Web 类(DB `config` 表 section="core")

```toml
# 用户偏好
language = "en"                     # 应用语言(报告/通知/UI 文本)
timezone = "UTC"                    # IANA 时区

[github]
gh_token = ""                       # SecretStr;空 → github 功能降级 + warning

[analysis]
provider = ""                       # Pydantic AI model 字符串,如 "anthropic";空 → AI 降级
model = ""                          # 如 "claude-sonnet-4";空 → 用 provider 默认
api_key = ""                        # SecretStr;空 → AI 降级
language = "en"                     # AI 输出语言

[markpost]
enabled = false                     # 显式开关
url = ""                            # SecretStr;enabled=true 但空 → 降级 + warning
max_batch_size = 1048576            # 业务字段(不同 MarkPost 服务上游限制不同)

[[notification.channels]]           # 经典 discriminated union 形态(见 10)
type = "console"                    # "console" | "email" | "feishu"
enabled = true

[[notification.channels]]
type = "email"
enabled = false
host = "smtp.example.com"
port = 465
user = "..."
password = "..."                    # SecretStr
from_addr = "..."
recipient = ["a@x.com", "b@x.com"]  # 多接收者
starttls = false
ssl = true

[[notification.channels]]
type = "feishu"
enabled = false
webhook_url = "..."                 # SecretStr

[observability.bugsink]
dsn = ""                            # SecretStr;空 → 错误收集降级
environment = "production"          # 部署环境标识

[web]
base_url = ""                       # 公网 base URL(报告回链用),用户可改
```

### 插件配置(DB `config` 表 section=插件 name)

**repo 插件(section="repo")**:
```toml
# 业务输入(列表型,[[repos]]/[[owners]])
[[repos]]
url = "vitejs/vite"
branch = "main"
enabled = true

[[repos]]
url = "facebook/react"

[[owners]]
type = "organization"               # "organization" | "user"
name = "bytedance"

[[owners]]
type = "user"
name = "torvalds"

# 调参
first_run_lookback_commits = 3      # 首次跑某 repo 回看 commit 数
```

**changelog 插件(section="changelog")**:
```toml
[[trackers]]
name = "Vite"
url = "https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"
parser_type = "markdown_heading"    # "markdown_heading" | "html_chinese_version"
enabled = true
```

**proposal 插件(section="proposal")**:
```toml
# kind 是 set 语义(启用哪些内置类型),列表最自然
trackers = ["eip", "erc", "pep", "rfc", "dep"]
```

### 列表型配置格式决策

列表型配置**保持 TOML array-of-tables**(`[[repos]]`/`[[owners]]`/`[[trackers]]`)和字符串列表(`trackers = ["eip",...]`)。

**决策理由**:
- TOML `[[array]]` 是一等公民,专为"同类多项"设计。
- Cargo.toml(`[[bin]]`/`[[bench]]`)、pyproject.toml(`[[project.authors]]`)都是列表型。
- MAP(key=标识)只在"key 是稳定自然标识且常被引用"时更优(如 Cargo deps)。我们的场景标识(url/name)就是字段本身,拿它再做 TOML key 是重复 + 脆弱(改 url 要改 key)。

**否掉的方案**:MAP 形态(`[repos.vitejs-vite]`)——增加配置复杂度(用户要造 key),且 key 与字段重复。

### notification channels 格式决策

采用**经典 discriminated union 形态** `[[notification.channels]] type = "email"`。

**决策理由**:实测 Pydantic 2.x 的 discriminated union 接受此形态(list-of-dicts with `type` key),TOML round-trip 干净,openapi schema 标准 oneOf+discriminator。

**否掉的方案**:`[[notification.channels.email]]`(type 为 key,下方多实例)——实测产生 `{channels:{email:[...]}}`(dict-of-lists),Pydantic discriminated union **拒绝**(期望 list-of-dicts)。多接收者需求由 email channel 内的 `recipient = [...]` 字段满足。

## 代码常量(移出 Config,进代码)

以下"调参项"用户几乎不改,移出 Config 进代码常量:

| 项 | 代码位置 | 值 |
|---|---|---|
| git 操作超时 | `cli/git/local.py` `GIT_TIMEOUT` | 300 |
| AI 调用超时 | `cli/ai/agent.py` `AI_TIMEOUT` | 600 |
| AI 重试次数/延迟 | `cli/ai/agent.py`(tenacity 配置) | 3 / 指数退避 |
| diff 截断阈值 | `cli/reports/pipeline.py` `MAX_DIFF_LENGTH` | 100000 |
| 截断保留字符 | `cli/reports/pipeline.py` `TRUNCATE_CHARS` | 200 |
| AI 并发数 | `cli/ai/agent.py` `AI_CONCURRENCY` | 1 |
| HTTP 超时 | `utils/http.py` `HTTP_TIMEOUT` | 30 |
| SMTP 超时 | `cli/notifications/channels/email.py` `SMTP_TIMEOUT` | 10 |
| OTel traces/metrics 开关 | `observability/telemetry.py` | 全开 |
| OTel 采样率 | `observability/telemetry.py` | 1.0 |
| DB pragmas | `db/`(代码固定) | WAL/NORMAL/busy_timeout=5000 等 |
| GitHub URL 模式/命令名等 | 各领域代码常量 | 固定 |

### 决策理由(代码常量 vs 动态配置的划分)

每项配置问"用户/部署者真的需要动态改这个吗":
- **真动态**(用户意图/凭据/业务输入)→ 进 Config(如 gh_token/repos/provider)。
- **实现细节/调参**(用户不关心)→ 进代码常量(如 timeout/retries/阈值)。

## Zero Configuration 实现

每个可选功能在缺失必要前提时**降级而非报错**。核心启动时检查各功能前提:

```
validate_feature_availability(cfg) -> FeatureAvailability:
  if not cfg.github.gh_token.get_secret_value():
    github = False; logger.warning("github.gh_token not set; GitHub tracking disabled")
  else: github = True

  if not cfg.analysis.api_key.get_secret_value() or not cfg.analysis.provider:
    ai = False; logger.warning("analysis provider/api_key not set; AI analysis disabled (truncation fallback)")
  else: ai = True

  if cfg.markpost.enabled and not cfg.markpost.url.get_secret_value():
    markpost = False; logger.warning("markpost.enabled=true but url empty; markpost publishing disabled")
  else: markpost = cfg.markpost.enabled
  ...
```

**系统照常跑**:无 github token → 不追踪 GitHub(只跑不依赖 GitHub 的 integration);无 AI key → 报告用截断降级;无 markpost → 只存 DB。每个功能独立可用性,互不阻塞。

## 接口设计(无歧义规范)

### 加载

```python
# config/loader.py
def load_config(config_path: str | None = None) -> CoreConfig:
    """
    加载配置。
    - config_path 为 None → 默认配置(zero config)
    - config_path 指定但文件不存在 → raise ConfigException(友好消息)
    - config_path 指定且存在 → pydantic 校验,失败 raise ConfigException(友好消息)
    """
```

### DB 配置读写(框架统一 API)

```python
# db/ 内的 config 读写(具体模块见 03)
async def get_config(section: str) -> dict:
    """读取某 section 的配置 JSON。不存在则返回 {}。"""


async def set_config(section: str, data: dict) -> None:
    """写入某 section 的配置。写入前用该 section 注册的 schema 校验。"""


async def get_all_config() -> dict[str, dict]:
    """读取所有 section,返回 {section: data}。前端 GET /config 用。"""
```

### Schema 导出

```python
# config/schema.py
@lru_cache
def get_config_json_schema() -> dict[str, dict]:
    """返回 {section: <JSON Schema>}。合并核心 schema + 各插件 schema。"""
```

### 种子导入

```python
# config/loader.py
async def seed_from_file(seed_path: Path, db_config: dict) -> dict:
    """
    合并种子与 DB 配置。优先级:DB > 种子。
    种子只填补 DB 中缺失的 key,不覆盖已有的。
    """
```

## 与 03(数据库)的接口

- `config` 表的 schema 定义、迁移、tortoise 模型见 03。
- 配置读写 API 的实现见 03(基于 tortoise 模型)。
- 本规范只定义配置的**逻辑模型和接口契约**。

## 与 12(API)的接口

- `GET /api/v1/config` → `get_all_config()`(SecretStr 自动脱敏)。
- `PUT /api/v1/config/{section}` → 校验 + `set_config()`。
- `GET /api/v1/config/schema` → `get_config_json_schema()`。
- 前端配置编辑器基于 schema 渲染表单(见 13)。
