# 05 · CLI 与编排

## 决策:Typer + 薄 CLI / 厚 `cli/core.py` 业务入口

CLI 框架 **Typer**(沿用)。CLI 只做参数解析 + Config 加载 + 调 `core.run_*()` + 退出码;**编排逻辑在 `cli/core.py`**,e2e 直调 `core.run_*()` 免 subprocess。

### Typer 决策理由

审计反馈用户倾向 Typer(生态最大、零迁移)。接受手写 `asyncio.run` 包装 boilerplate(Typer 无 native async)。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| Cyclopts | native async 省 boilerplate,但单维护者 bus factor + 生态小;用户选 Typer |
| Fire | 半休眠、无 async、无 pydantic 集成 |
| bare Click | 与 Typer 等价但更多 boilerplate,无收益 |

## 命令面(收敛)

最终命令面仅两个,后续按需加:

| 命令 | 职责 | 入口 |
|---|---|---|
| `progress run` | 全量追踪(调度所有 integration 的 sync+run + 报告 + 通知) | `cli/core.py` `run()` |
| `progress serve` | 起 API 服务(uvicorn) | `progress.api.main:app` |

- **裸跑 `progress`(无子命令)→ 显示帮助**(需显式 `run`)。
- **删除** `config import`(改约定文件触发,见 02)、`config export`(后续按需)、`track-proposals`(并入 `run --only proposal` 或类似,后续优化)。

### 决策理由

简单为主,后续有需求再逐步拓展参数、优化行为。

## 薄 CLI / 厚 core.py 模式

### 模式说明(经典 pattern)

CLI 只负责解析配置和参数,处理后调用入口函数跑真正逻辑。业务逻辑测试只测入口函数;e2e 测试构造参数调入口函数,避免 subprocess run。

### 文件职责

```
src/progress/cli/
├── __init__.py     # 空(仅包标记,无 import — 防循环依赖,见下)
├── main.py         # typer app + 命令定义(薄,入口模块)
├── core.py         # ★ run_*() 业务入口(厚,e2e 直调)
├── lifespan.py     # @asynccontextmanager(CLI 进程生命周期)
└── outcome.py      # RunOutcome 结构化结果
```

> **`__init__.py` 必须保持空**:它会被 API import 路径(`config.root →
> cli.notifications.config`)触达。若在 `__init__.py` 顶层 import
> `cli.core`/`cli.users`,会拉起 `cli.core → cli.lifespan → config.loader`,
> 与正在初始化的 `config.loader` 成环,炸 `from progress.api import
> create_app`。Typer app 与命令定义放在 `cli/main.py` —— 这是 Typer 官方文档
> + typer/fastapi/fastapi-cli/httpx/ruff/uv 一致的入口模块惯例。`__main__.py`
> 与 `[project.scripts] progress = "progress.cli.main:app"` 都指向它。
>
> **回归门控**:`scripts/check_drift.py` 的 OpenAPI drift 检查每次跑
> `from progress.api import create_app`,任何让循环依赖回归的改动都会让
> `export_openapi.py` 炸,该检查立刻 FAIL。(import-linter 的 `forbidden`
> 契约无法表达"`__init__.py` 这个文件不能 import 自身子模块"——父包到子模块
> 的 import 被视为重叠模块自动跳过——所以门控靠 check_drift 而非 lint-imports。)

### `cli/main.py`(薄 CLI 入口模块)

```python
app = typer.Typer(invoke_without_command=False)   # 裸跑显示帮助

@app.command()
def run(
    config: str = typer.Option("config.toml", "--config", "-c"),
    trackers_only: bool = typer.Option(False, "--trackers-only"),
):
    """Run full tracking pipeline."""
    cfg = load_config(config)                     # 解析参数 + 加载配置
    outcome = asyncio.run(core.run(cfg, trackers_only=trackers_only))  # 调厚核心
    raise typer.Exit(code=outcome.exit_code)      # 转 exit code

@app.command()
def serve(...):
    """Start API server (uvicorn)."""
    ...
```

**CLI 不碰** DB/telemetry/编排——这些在 `core.py` + `lifespan.py`。

### `cli/core.py`(厚核心,e2e 直调)

```python
async def run(cfg: CoreConfig, *, trackers_only: bool = False) -> RunOutcome:
    """业务编排入口。e2e 可直调: outcome = await run(cfg)。"""
    async with lifespan(cfg, component="cli") as ctx:  # 起 DB + telemetry + integrations
        outcome = RunOutcome()
        for integration in discover_integrations():  # 从注册表发现(见 06)
            await integration.setup(ctx)
        for integration in discover_integrations():
            await integration.sync()  # 配置→状态同步 + GC
            result = await integration.run()  # 实际追踪 + 分析 + 持久化
            outcome.add(integration.name, result)
        for integration in discover_integrations():
            await integration.teardown()
        return outcome
```

### `core.py` 职责边界(强制,防变 God 函数)

**只做编排**:按序调度 integration 的钩子 + 收集结果 + 管生命周期。**不含业务逻辑**(业务在各 integration 的 tracker.py)。这呼应 09 reports 的 pipeline.run 同理。

### `cli/lifespan.py`

```python
@asynccontextmanager
async def lifespan(cfg: CoreConfig, *, component: str) -> AsyncIterator[Components]:
    """CLI 进程生命周期:起 DB engine + OTel + i18n → yield Components → cleanup。"""
    await init_db(cfg.state_home)
    tortoise_migrate()
    setup_observability(cfg.observability, component=component)
    initialize_i18n(cfg.language)
    session = aiohttp.ClientSession()              # 每入口点各自管 session(见 07)
    try:
        yield Components(session=session, cfg=cfg, ...)
    finally:
        await session.close()
        shutdown_observability()
        await close_db()
```

- **yield 类型化 `Components` 对象**(dataclass),替代当前无类型 5 元组(`bootstrap.py` 的 `(cfg, markpost_client, repo_manager, proposal_tracker, reporter)`)。
- **CLI 和 API 各自独立的 lifespan**(都基于共享 `db/`、`observability/`)。

## 退出码语义

```python
# cli/outcome.py
@dataclass
class RunOutcome:
    results: dict[str, RunResult]  # {integration_name: result}
    errors: list[ProgressException]  # 收集的错误

    @property
    def exit_code(self) -> int:
        if not self.errors:
            return 0  # 全成功
        return 1  # 部分失败
```

- **0** = 全成功。
- **非零** = 部分失败(如 1)。
- **配置错误** = 特定码(如 2),`ConfigException` → `typer.Exit(code=2)`。
- **编排层不裸抛意外异常**:`core.run` 区分 `ProgressException`(业务错误,结构化收集)与意外异常(上抛)。

### 决策理由

修当前 `cli.py:150-157` 的 `except Exception` 把编程错误(TypeError/AttributeError)降级成用户错误的病根。

## 删除清单

| 删除 | 理由 |
|---|---|
| `orchestration.py`(247 行) | CLI 副本,并入 `cli/core.py` |
| `bootstrap.py`(78 行) | 无类型 5 元组,并入 `cli/lifespan.py` |
| `_run_async` 包装散落 | 统一到命令级 `asyncio.run` |
| 隐式默认命令(裸跑=check) | 改为显示帮助 |
| `track-proposals` 独立命令 | 并入 `run` 参数,后续优化 |
| 每命令重复 `finally: close_db()` | 统一到 lifespan |

## 与 06(插件)的接口

`core.run()` 调用 `discover_integrations()` 从注册表发现所有 integration(见 06),按统一钩子 `setup → sync → run → teardown` 调度。核心对 integration 完全透明——新增 integration 只需 `@register` + 实现 4 钩子,核心零改动。
