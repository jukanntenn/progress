# 12 · FastAPI 服务端

## 决策:app factory + lifespan + 中间件(dev CORS)+ 无认证 + 端点设计 + openapi 静态导出

FastAPI 作为与 CLI 对称的 HTTP 入口包 `api/`,自包含 lifespan + 中间件,**无应用层认证**(信任网络边界),RESTful 端点,Pydantic response_model 为 OpenAPI 单一真相源。

## app factory

```python
# api/__init__.py
def create_app(config_path: str | None = None) -> FastAPI:
    """构建 FastAPI app。延迟构建,不在 import 时裸抛。"""
```

- `api/main.py`:`app = create_app()`(ASGI 入口,`uvicorn progress.api.main:app`)。
- **CLI `progress serve`** 子命令封装 uvicorn 编程式启动(`uvicorn.run`/`Server`,见 05)。
- **修当前病根**:当前 `main.py:3` `app = create_app()` 在 import 时构建,配置缺失/非法时导入即抛,`fastapi run` 还没打日志就崩。

## lifespan(修当前多个 bug)

```python
# api/__init__.py
@asynccontextmanager
async def _lifespan(app: FastAPI):
    # startup(try/except 结构化错误到 Bugsink)
    try:
        cfg = load_config(config_path)
        await init_db(cfg.state_home)
        tortoise_migrate()
        register_tortoise(app, ...)  # FastAPI 集成
        setup_observability(cfg.observability, component="api")
        instrument_fastapi_app(app)  # ★ 在 setup_observability 之后(修顺序 bug)
        load_config_from_db()  # 加载 config 表(种子合并,见 02)
        session = aiohttp.ClientSession()  # API 自己的 session(见 07)
        app.state.session = session
    except Exception as e:
        report_error(e)
        raise
    try:
        yield
    finally:
        await session.close()
        shutdown_observability()
        await close_db()
```

### 修当前病根

| 病根 | 修复 |
|---|---|
| lifespan 启动步骤无 try/except,失败裸抛 | try/except 结构化错误到 Bugsink |
| `setup_observability` 在 DB 步骤之后(启动失败到不了 Bugsink) | 提前,且 instrument 在 setup 之后 |
| `instrument_fastapi_app` 在 `create_app` 时调用,`_STATE.enabled=False` early-return(span 永不产生) | 移到 lifespan setup 完成后 |

## 中间件栈

| 中间件 | 说明 |
|---|---|
| **GZipMiddleware** | 压缩 |
| **SecureASGIMiddleware**(`secure` 包) | 安全头(CSP/HSTS/X-Frame-Options/X-Content-Type-Options/Referrer-Policy)。HSTS 仅 TLS 时开 |
| **CorrelationIdMiddleware**(`asgi-correlation-id` snok) | 请求 ID,注入 Sentry |
| **CORSMiddleware** | **仅 dev 开**(见下) |
| TrustedHostMiddleware | 超 loopback 时 |

### CORS 仅 dev(修过度设计)

**生产 Caddy 单源**(前端后端同 :5000)→ **零跨源请求**,CORS 是死代码 + 扩大攻击面。

- **dev 开**:Vite :5173 vs FastAPI :8000 跨源,需 CORS。
- **生产不注册**:用 env 标志(`PROGRESS_DEV_CORS=1`)或检测 Vite 独立 origin,才加 CORSMiddleware + 显式 allowlist。

**否掉**:CORSMiddleware 常开(死代码 + `allow_origins=["*"]`+`allow_credentials=True` 不安全组合)。

## 无应用层认证(YAGNI)

**默认无认证**。自托管单用户/内网信任模型,应用层不认证。

- **删** `api.auth_token` 配置项 + HTTPBearer + compare_digest(不进 config 表也不进文件)。
- 安全依赖:网络边界(Caddy loopback / 内网 / 反代层认证)。
- `/docs` + `/openapi.json` 可公开(无敏感信息——openapi schema 只含字段形状,不含 secret 值)。

### 决策理由

- 自托管工具默认信任网络边界。
- YAGNI:不预先设计不需要的功能;未来若需暴露公网再加认证层。
- 呼应 zero configuration。

### 否掉的方案

| 方案 | 否掉理由 |
|---|---|
| HTTPBearer + 单 token | YAGNI;无认证需求时不增加复杂度 |
| HttpOnly cookie session | 当前无认证需求,cookie session 是认证方案之一,非必需 |

### CSRF 随之消失

无认证 + 无 cookie session → **无 CSRF 攻击面**(CSRF 只在 cookie session 认证时才是风险)。

## 端点设计(RESTful)

```
配置管理(见 02):
  GET    /api/v1/config                    → {core:{...}, repo:{...}, ...}(SecretStr 自动脱敏)
  PUT    /api/v1/config/{section}          → 校验后写 config 表
  GET    /api/v1/config/schema             → {core:<schema>, repo:<schema>, ...}
  POST   /api/v1/config/reload             → 重载配置(可选)

报告(只读已落库):
  GET    /api/v1/reports                    → 分页列表(?page=&page_size=)
  GET    /api/v1/reports/{id}              → 单报告详情(含 rendered HTML)
  GET    /api/v1/reports/{id}/raw          → 原始 markdown(可选)

integration 数据(插件经注册表自动暴露):
  GET    /api/v1/integrations              → 已注册 integration 列表
  GET    /api/v1/integrations/{name}/status → 某 integration 状态

RSS:
  GET    /api/v1/rss                        → RSS feed(feedgen)

系统:
  GET    /healthz                           → liveness(免认证,{"status":"ok"})
  GET    /readyz                            → readiness(ping DB,免认证)
  GET    /api/v1/version                    → 版本信息(可选)
```

### 资源命名:`reports`(复数)

- REST 惯例 + 与表名 `reports`(03)一致。
- `GET /reports`(列表)、`/reports/{id}`(单个)。

## 统一约定

### 所有响应 `response_model`(Pydantic)

- 运行时校验 + OpenAPI 自动完整(`fastapi/routing.py:293-333`)。
- **单一真相源**:前端类型从 `/openapi.json` 生成(见 13),永不手写。

### 统一错误信封

```json
{"error": {"code": "...", "message": "...", "details": {...}}}
```

全局 exception handler,`api/errors.py`。

### 统一分页

```json
{"items": [...], "page": 1, "page_size": 20, "total": 100, "has_next": true}
```

`page`/`page_size` 有上限校验。

### timezone 用 zoneinfo 校验

`timezone_str` 查询参数用 `zoneinfo` 校验(与后端一致),修当前 pytz/zoneinfo 不一致。

## markdown 安全

`api/markdown.py`:`html=True` + nh3 sanitize(09 已定)。修存储型 XSS。

## 事务一致性

`replace_*` 端点统一用 `in_transaction()`(03 已定),修当前 `replace_owners` 非原子 vs `replace_repositories` 用事务的不一致。

## OpenAPI 静态导出(修 workflow gap)

`openapi-typescript [input]` 接受**文件或 URL**,不能内省 Python app。CI 不跑 uvicorn。故:

```python
# scripts/export_openapi.py
from progress.api import create_app

app = create_app()
import json

with open("web/openapi.json", "w") as f:
    json.dump(app.openapi(), f, indent=2)  # app.openapi() 返回 dict(同步,无需起 server)
```

- `web/openapi.json` **提交为契约 artifact**。
- CI:重生成 + diff(schema drift)+ `openapi-typescript web/openapi.json --check`(type drift)。
- 前端:`openapi-typescript web/openapi.json -o src/api/schema.ts` 生成类型。

## 限流

slowapi 应用到写端点(防滥用)。源码核实:`Limiter` 默认内存后端(`extension.py:243-245` `memory://`);FastAPI 模式是 `app.state.limiter = limiter` + `add_exception_handler(RateLimitExceeded, ...)` + `@limiter.limit`(**注**:无 `init_app`,那是 Flask-Limiter)。

## 文件结构

```
src/progress/api/
├── __init__.py     # create_app + lifespan + 中间件装配
├── main.py         # app = create_app()(ASGI 入口)
├── routes/         # {config,reports,integrations,rss,system}.py
├── deps.py         # Depends:get_session/get_config
├── middleware.py   # GZip/Secure/CorrelationId/CORS(dev)
├── errors.py       # 异常→HTTP 映射 + 统一错误信封
├── schemas.py      # 共享 Pydantic response models
└── markdown.py     # markdown-it-py + nh3
```

## 删除清单

| 删除 | 理由 |
|---|---|
| import 时构建 app | 延迟 + 友好错误 |
| FastAPI 插桩顺序 bug | lifespan setup 后 |
| 无 CORS / 常开 CORS | 仅 dev |
| API 无认证(已是现状) | 保持无认证,删 auth_token 设计 |
| 路由手动两处维护 | 注册表 |
| 裸 dict 返回(无 response_model) | 全 response_model |
| `replace_owners` 非原子 | 统一 in_transaction |
