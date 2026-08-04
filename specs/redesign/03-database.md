# 03 · 数据库

## 决策:tortoise-orm(async)+ aiosqlite + SQLite,内置迁移

ORM 选型 **tortoise-orm**(沿用),配 aiosqlite 驱动、SQLite 后端、tortoise 内置 migrations。

### 选型核实证据(源码事实)

| 需求 | tortoise 支持 | 证据 |
|---|---|---|
| 强类型(满足 ty/pyright) | ✅(需改字段声明风格) | 实测 `ty check`:当前 `id: int = IntField()` 风格必然报错;**bare 风格 `id = IntField()`(无注解)零错误**,实例访问正确推断。tortoise 自身 testmodels 即此风格 |
| 每 app 自带 migrations + 自动生成 | ✅ | `tortoise/cli/cli.py` 有 makemigrations/migrate/upgrade/downgrade + autodetector;`examples/multiapp_migrations_project/` 实证三 app 各自 migrations/ |
| 跨 app FK 依赖 | ✅ | `migrations/autodetector.py:115-136` `_relation_dependencies` 自动加跨 app 依赖 |
| 动态发现 entry_points 模型 | ✅ | `apps.py:45-52` `_discover_models` 接受 `ModuleType`;`__init__.py:285` `modules: dict[str, Iterable[str | ModuleType]]` |
| JSON 字段 + pydantic | ✅(浅) | `fields.JSONField`;`field_type=PydanticModel` 自动序列化/反序列化 |
| async + 连接管理 | ✅ | contextvars `TortoiseContext`,`in_transaction()`,`register_tortoise`(FastAPI 集成) |
| bulk/indexes/FK | ✅ | 全支持 SQLite |

### 决策理由

1. **满足全部需求**(上表)。
2. **类型债可消**:改字段声明为 bare 风格(`id = fields.IntField()` 无注解)即可消除当前 51 个 `# ty: ignore`。这是写法问题,非库缺陷。
3. **迁移是核心痛点**:当前手写 130 行迁移是最大风险;tortoise 内置迁移 + 每 app 自带 + 跨 app FK 自动依赖,正好解决。
4. **全新设计零迁移包袱**:无需数据迁移,直接建新 schema。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| SQLAlchemy 2.x async + Alembic | 能力更强但:重写 8 模型 + 重学 AsyncSession 生命周期(非并发安全,一任务一会话);tortoise 已满足需求,无净收益 |
| SQLModel | pre-1.0,锁 SQLAlchemy 版本,关系处理粗糙;thin 层无实质收益 |
| Aerich | tortoise 1.x 内置迁移后 Aerich 多余(`README.md:9-13` 明示) |
| PonyORM/Peewee | 无 async 故事 |
| raw aiosqlite + query builder | 重建连接池/行映射/迁移 diffable schema,成本高于 ORM 收益 |

### 接受的代价

1. **字段无注解**(bare `id = fields.IntField()` 风格)——风格改变,可接受。
2. **无 app 内多目录迁移**——但"每 app 一个 migrations/"满足需求,不需要 app 内再分目录。
3. **Alpha 状态 + 467 open issues**——迁移子系统在快速硬化,可用但非久经考验;社区活跃、方向正确,风险可控。

## 数据模型总览

### 配置(统一 `config` 表,见 02)

| 表 | 列 | 说明 |
|---|---|---|
| `config` | `section` PK str, `data` JSON, `updated_at` datetime | 分区存核心 + 插件配置 |

### 核心状态(核心运行产物)

| 表 | 列 | 说明 |
|---|---|---|
| `reports` | id, report_type, repo_id FK(nullable), title, commit_hash, previous_commit_hash, commit_count, markpost_url, content, created_at | 生成的报告(报告**默认存 DB**,见 02 删 storage 概念) |
| `batches` | id, report_id FK, title, markpost_url, seq, created/updated_at, unique(report_id, seq) | 多批报告的一批(markpost 上传) |

### 插件状态(各插件自带,见 06)

每插件在自己的 `models.py` 定义状态模型(Django app 式自治):

| 插件 | 模型 | 说明 |
|---|---|---|
| repo | `Repository`, `GitHubOwner` | 跟踪的 repo + 检查点 + release 检查点;监控的 owner |
| changelog | `ChangelogTracker` | changelog 源 + 检查点 |
| proposal | `ProposalTrackerState`, `Proposal` | proposal 检查点 + 提案状态 |

### 配置 vs 状态分离(核心原则)

- **配置**(用户意图声明):统一 `config` 表,Web 整体读写。
- **状态**(系统运行产物):各领域自带表,系统写、Web 只读。
- **当前病根**:把 `repos` 配置和 `Repository.last_commit_hash` 状态塞同一张表。新设计严格分离。

## tortoise 模型规范

### BaseModel

```python
# db/base.py
class BaseModel(Model):
    """抽象基类。声明 updated_at 的模型在 save 时自动刷新。"""

    class Meta:
        abstract = True
```

### 字段声明风格(强制,bare 无注解)

**必须**用 bare 风格消除类型债:

```python
# ✅ 正确(bare,无注解,ty 零错误)
class Repository(BaseModel):
    id = fields.IntField(primary_key=True)
    name = fields.CharField(max_length=255)
    url = fields.CharField(max_length=255, unique=True)
    last_commit_hash = fields.CharField(max_length=255, null=True)
    created_at = fields.DatetimeField(default=now_utc)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "repositories"
```

```python
# ❌ 错误(带注解,必然 ty: ignore)
class Repository(BaseModel):
    id: int = fields.IntField(primary_key=True)  # ty: ignore[invalid-assignment]
    name: str = fields.CharField(max_length=255)  # ty: ignore[invalid-assignment]
```

### `config` 表模型

```python
# db/models/config.py(核心状态模型包内)
class Config(BaseModel):
    section = fields.CharField(max_length=64, primary_key=True)
    data = fields.JSONField(default=dict)
    updated_at = fields.DatetimeField(default=now_utc)

    class Meta:
        table = "config"
```

## 迁移规范

### 每 app 自带 migrations/

每个"app"(核心 + 每个 integration)有自己的 migrations 目录:

```
src/progress/db/migrations/           # 核心 migrations
src/progress/integrations/repo/migrations/
src/progress/integrations/changelog/migrations/
src/progress/integrations/proposal/migrations/
```

### tortoise CLI 配置(CLI 与运行时同源)

**必须**提供 `TORTOISE_ORM` dict,CLI 与运行时 `Tortoise.init` **共享同一 modules 列表**(含插件 models),否则迁移与 live schema 漂移。

```python
# db/tortoise_config.py
TORTOISE_ORM = {
    "connections": {"default": "sqlite://..."},
    "apps": {
        "core": {
            "models": ["progress.db.models", "progress.integrations.repo.models", ...],
            "default_connection": "default",
        },
    },
}
```

- CLI 用 `tortoise makemigrations -c progress.db.tortoise_config.TORTOISE_ORM`。
- 运行时 `Tortoise.init(modules=...)` 的 modules 列表与 `TORTOISE_ORM` **同源**(从同一处导出)。
- 插件 models 经 entry_points 发现后加入此列表(见 06)。

### 删除手写迁移

**删除**当前 `db/__init__.py:127-271` 的 `migrate_database()`(130 行手写 ALTER/DROP/CREATE)。**删除** `generate_schemas(safe=True)` 做生产建表(tortoise 自称 not-for-production)。全部改用 tortoise 内置迁移。

### 迁移命令

```
tortoise makemigrations     # 检测模型变化,生成迁移
tortoise migrate            # 应用迁移到 DB
tortoise upgrade/downgrade  # 升级/回滚
```

启动时自动 `tortoise migrate`(在 lifespan 内)。

## 连接管理

### FastAPI 路径:register_tortoise

API 用 `tortoise.contrib.fastapi.register_tortoise(app, ...)`(专为 FastAPI lifespan 设计,`contrib/fastapi/__init__.py:208-305`)。

```python
register_tortoise(
    app,
    config=TORTOISE_ORM,
    _enable_global_fallback=True,  # 单 app SQLite 安全
)
```

### CLI 路径:显式 init/close

CLI 在 `cli/lifespan.py` 的 `@asynccontextmanager` 内显式 `Tortoise.init` + `close_connections`(见 05)。

### 事务纪律

**所有多语句写入必须包 `in_transaction()`**:

```python
async with in_transaction():
    await Report.create(...)
    await Batch.bulk_create(...)
```

修当前 `publish_report` 多行写入无事务的病根。

### SQLite pragmas(代码固定)

PRAGMAs 通过 tortoise URL query string 或 connect 事件设置(代码固定,不可配):

```
journal_mode=WAL, synchronous=NORMAL, busy_timeout=5000, foreign_keys=ON, cache_size=-64000
```

## 接口设计

```python
# db/__init__.py
async def init_db(state_home: str) -> None:
    """初始化 DB 连接 + 应用迁移。db_path = <state_home>/progress.db"""


async def close_db() -> None:
    """关闭所有连接。"""


# 配置读写 API(02 定义的契约在此实现)
async def get_config(section: str) -> dict: ...
async def set_config(section: str, data: dict) -> None: ...
async def get_all_config() -> dict[str, dict]: ...
```

## 删除清单

| 删除 | 理由 |
|---|---|
| `db/__init__.py` `migrate_database()`(130 行手写) | 改用 tortoise 内置迁移 |
| `generate_schemas(safe=True)` 生产建表 | tortoise 自称 not-for-production |
| `database_connection()` 误导命名 | 直接用 `in_transaction()` |
| `save_report()` 的 `config` 死参数 | 清理 |
