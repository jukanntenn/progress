# 07 · Git 与 HTTP 客户端

## 决策:gidgethub(GitHub API)+ asyncio subprocess(本地 git)+ 统一 aiohttp(HTTP)

### 三个子决策

| 关注点 | 选型 | 理由 |
|---|---|---|
| GitHub API | **gidgethub**(aiohttp adapter) | async-native,自动分页,限流追踪;删 PyGithub + 7 处 to_thread |
| 本地 git | **asyncio subprocess** 调 git CLI | 调研证实无 async-native git 库(dulwich/pygit2/GitPython 全 sync,无 sans-IO git 库),subprocess 是 2026 最佳 |
| 通用 HTTP | **统一 aiohttp** | httpx 停滞(19 月无 release/issue 关闭);aiohttp 活跃(505 commits/3 月);gidgethub 原生 aiohttp adapter |

## GitHub API:gidgethub

### 选型理由(源码核实)

- **async-native**:`gidgethub.aiohttp.GitHubAPI`(`aiohttp.py:9-14` 构造接 `aiohttp.ClientSession`)。
- **自动分页**:`getiter()` follow `next` 链接(`abc.py:172-198`),删当前手写 `_list_releases_sync`/`_list_repos_sync` 分页。
- **内置限流追踪**:`rate_limit` 从 header 自动追踪(`sansio.py:270-283` 优雅处理缺 header),删 6 方法复制的 `RateLimitExceededException` try/except。
- **sans-IO 核心**:`gidgethub.sansio` 可独立测试(无需网络)。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| PyGithub + to_thread | sync 库硬桥接 async,丢失并发性 |
| github3.py | 同样 sync requests-based,无优势 |

## 本地 git:asyncio subprocess

### 选型理由(调研核实)

- **无 async-native git 库**:dulwich/pygit2/GitPython 全 sync;dulwich 唯一 async 是 server 端 `to_thread` 包装;无 sans-IO git 库。
- **async-clean**:`asyncio.create_subprocess_exec` 原生 async,删 17 处 to_thread。
- **无 index.lock 风险**:每次 subprocess 独立,无 in-process lib 状态(修当前 GitPython 的 index.lock 脆弱补丁)。
- **超时/取消天然**:subprocess timeout/cancel 比 GitPython 干净。
- **与现有代码一致**:`_run_git_command_sync` 已 shell-out,统一为纯 subprocess 更简。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| 保留 GitPython | sync + index.lock 脆弱(已有 `_cleanup_git_locks_sync` 补丁) |
| dulwich + to_thread | sync,async 语义被破坏 |

## 通用 HTTP:统一 aiohttp

### 选型理由(调研核实,httpx 停滞的关键证据)

- **httpx 停滞**:最新 release 0.28.1 是 2024-12-06(19 月前);近 3 月 0 commits;**issue tracker 已禁用**(`has_issues: false`)。
- **aiohttp 活跃**:3.14.1(2026-06-07),近 3 月 505 commits,近 12 月 9 release。
- **gidgethub 原生 aiohttp adapter**:无需两库并存。
- **OTel `AioHttpClientInstrumentor` 不变**:04 已定,无反向影响。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| httpx | 停滞(issue 关闭、19 月无 release) |
| httpx2(pydantic 继任者) | 2 月龄、生态(OTel/respx)未验证,风险高 |
| requests | sync,违背 async |

## aiohttp ClientSession 生命周期(关键规范)

**每入口点各自管 session,不跨进程共享**。

### 决策理由

- CLI(短命,`asyncio.run`)与 API(长驻)生命周期不同。
- 全局 session 跨 `asyncio.run` 调用会 "attached to a different loop"。
- aiohttp ClientSession 应在 event loop 内创建。

### 接口设计

```python
# utils/http.py
@asynccontextmanager
async def session_factory(timeout: int = HTTP_TIMEOUT) -> AsyncIterator[aiohttp.ClientSession]:
    """异步上下文管理器:创建 session → yield → close。每入口点各自调用。"""
    session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout))
    try:
        yield session
    finally:
        await session.close()
```

- **CLI**:`cli/lifespan.py` 内 `async with session_factory() as session:` yield 给编排。
- **API**:`api/__init__.py` lifespan 内同上。
- **修当前病根**:审计证实 feishu/email/markpost 每次 `send()` 新建 session(无连接池复用)。

## OTel 插桩时序(关键约束)

`AioHttpClientInstrumentor().instrument()` 包装 `ClientSession.__init__`(`__init__.py:681-683`)注入 TraceConfig。

**强制时序**:`.instrument()` **必须**在创建 `aiohttp.ClientSession` **之前**调用,否则 session 无 TraceConfig,调用不被追踪。

- 在 `setup_observability()` 内调用 `.instrument()`(早于任何 session 创建)。
- 或在创建 session 时显式 `trace_configs=[create_trace_config()]`(`__init__.py:327-629`,无论 instrument 时序都有效)。

## 错误契约统一

- gidgethub 统一异常契约(删当前 `get_pr_title_sync` 对 RateLimit 返回 None vs 其余 raise GitException 的不一致)。
- 本地 git subprocess 统一 `CommandException`(修当前 `@retry(exceptions=(GitException,))` 永不触发的死代码——实际抛 `CommandException` 非子类)。

## 安全修复

| 病根 | 修复 |
|---|---|
| token 记日志前 8 字符 | 删日志记录 token 片段 |
| `_configure_proxy` 全局改 `os.environ` | 改 aiohttp session 级 proxy(`ClientSession(proxy=...)`) |
| `REPO_URL_PATTERNS` 正则 `\.?git?` bug(末尾 t 可选) | 修正则 |

## 文件结构

```
src/progress/cli/git/
├── __init__.py
├── github.py     # gidgethub GitHubAPI 封装(releases/repos/readme/PR)
├── local.py      # asyncio subprocess git 操作(clone/fetch/diff/log)
└── url.py        # URL 解析(修复正则 bug)
```

## 重试:tenacity

统一用 tenacity(`@retry` 自动检测 async,`tenacity/__init__.py:752`),`wait_exponential_jitter`,替代当前手写 `aretry`(`utils/functional.py` 45 行无 jitter)。

```python
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

@retry(stop=stop_after_attempt(AI_RETRIES),
       wait=wait_exponential_jitter(initial=AI_RETRY_DELAY, max=60),
       retry=retry_if_exception_type(TransientError))
async def fetch_release(...): ...
```

## 删除清单

| 删除 | 理由 |
|---|---|
| `git/client.py`(GitPython + CLI 混用) | 统一 subprocess |
| `git/github_client.py`(PyGithub + to_thread) | 改 gidgethub |
| `utils/functional.py` retry/aretry | 改 tenacity |
| `_handle_git_retry` 死代码 | retry 永不触发 |
| token 日志泄漏 | 安全 |
| 全局 proxy env | 改 session 级 |
