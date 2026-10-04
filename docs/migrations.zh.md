# 数据库迁移

[English](migrations.md) | 中文

Progress 使用 [tortoise-orm](https://github.com/tortoise/tortoise-orm) 内置的迁移 CLI（命令行界面，`python -m tortoise`）。Aerich 不支持 tortoise-orm ≥1.0，本项目**不**使用它。

迁移按应用存放，与各应用的模型同目录：

| 应用标签 | 迁移目录 |
|-----------|----------------------|
| `core` | `src/progress/db/migrations/` |
| `repo` | `src/progress/integrations/repo/migrations/` |
| `changelog` | `src/progress/integrations/changelog/migrations/` |
| `proposal` | `src/progress/integrations/proposal/migrations/` |
| `feed` | `src/progress/integrations/feed/migrations/` |

应用标签由 `src/progress/db/tortoise_config.py` 中的 `build_tortoise_config()` 派生，因此新集成只要注册了 `models_module` / `migrations` 包就会被自动纳入。

## 包装脚本

`scripts/migration.py` 包装了冗长的 `uv run tortoise -c progress.db.tortoise_config.TORTOISE_ORM ...`。请使用它，不要直接调用 tortoise：

| 命令 | 作用 |
|---------|--------------|
| `make <name>` | 从模型变更生成迁移（`<name>` 必填，须有语义）。 |
| `apply` | 把待处理的迁移应用到数据库。 |
| `sql <app> <id>` | 打印某个迁移的 SQL（预览，不改数据库）。 |
| `down <app> [id]` | 回滚；默认回滚到上一个迁移。 |
| `drift` | 重新生成、与已提交文件比对、再还原；发现漂移时以非零码退出。 |

## 工作流

### 1. 修改模型

在所属包里编辑 tortoise 模型（例如 `src/progress/db/models/report.py`）。

### 2. 生成迁移

```bash
uv run python scripts/migration.py make add_report_index
```

`<name>` 必填，并成为文件名的一部分（`0002_add_report_index.py`）。始终使用有语义的名字，绝不提交默认的时间戳名字。

### 3. 应用前预览 SQL

```bash
uv run python scripts/migration.py sql core 0002_add_report_index
```

检查输出，确认生成的 DDL 与意图一致。

### 4. 本地应用

```bash
uv run python scripts/migration.py apply
```

启动（`init_db`）也会自动应用待处理的迁移，因此下一次 `uv run progress run` / `serve` 同样会应用它们。

### 5. 提交迁移文件

新的 `migrations/<app>/000N_<name>.py` 是源码产物：与模型变更一起提交。一个模型变更 = 一个迁移文件。

### 6. CI 检查漂移

`ci.yml` 的 drift-checks 作业运行 `scripts/migration.py drift`：先对已提交的迁移做快照，再重新生成并比对。没有配套迁移文件的模型变更会让检查失败：

```
migration drift detected: run `uv run python scripts/migration.py make <name>`
and commit the generated migration.
```

推送前在本地运行 `drift`，尽早发现问题：

```bash
uv run python scripts/migration.py drift
```

## 回滚

```bash
uv run python scripts/migration.py down core                 # previous migration
uv run python scripts/migration.py down core 0001_initial    # specific target
```

降级会改动数据库 schema；磁盘上的迁移文件**不会**被删除。

## 新增集成应用

新集成注册 `models_module` 与 `migrations` 包后，其应用标签会自动出现在 `build_tortoise_config()["apps"]` 里。用该应用标签生成初始迁移：

```bash
uv run python scripts/migration.py make initial
```

包装脚本从实际生效的配置推导迁移目录，因此 `drift` 会自动纳入新应用，无需更新任何硬编码列表。
