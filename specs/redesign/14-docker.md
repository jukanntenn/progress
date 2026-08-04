# 14 · Docker

## 决策:2 进程架构(Caddy + uvicorn)+ 非 root + 静态 serve + 全面加固

容器仅 **2 进程**(Caddy serve 前端静态 + 反代 API;uvicorn 跑 FastAPI)。删 node 运行时(Vite 产静态)。非 root 运行 + 全面加固。

## 服务架构(2 进程)

```
外部请求 → Caddy(:5000,s6 longrun)
             │
             ├─ /api/* → reverse_proxy 127.0.0.1:8000(FastAPI/uvicorn,s6 longrun)
             │
             └─ 其他 → root * /app/web/dist; try_files {path} /index.html; file_server
                       (前端 Vite 静态 + SPA 回退)
```

### 删 node 运行时(⑬ 连带)

- Vite 产 `dist/`(纯静态 HTML/CSS/JS),Caddy 直接 serve。
- **镜像不需要 nodejs/npm**(彻底删,非"删 AI CLI 但留 node")。
- **删 nextjs s6 服务**(无 node server)。
- 仅保留 `caddy` + `fastapi` 两个 s6 longrun。

### 决策理由

- 前端是 Vite SPA(⑬),无 node server 需求。
- 2 进程架构最简(Caddy serve 静态 + 反代;uvicorn 跑 API)。
- Caddy `try_files {path} /index.html` 单回退规则覆盖所有前端路由(含运行时动态 `/reports/123`)。

## 镜像加固(修 5 个 HIGH)

### 非 root 运行

```dockerfile
RUN addgroup -S progress && adduser -S -G progress progress
RUN mkdir -p /app/data && chown -R progress:progress /app
USER progress
```

### digest 锁 + SHA256 校验

```dockerfile
FROM python:3.13-alpine@sha256:<digest>    # digest 锁(非浮动 tag)

# 二进制 SHA256 校验
RUN curl -fsSL <url> -o /tmp/caddy && \
    echo "<expected-sha256>  /tmp/caddy" | sha256sum -c - && \
    install /tmp/caddy /usr/local/bin/
```

### HEALTHCHECK

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:5000/healthz"]
```

### compose 加固

```yaml
services:
  progress:
    user: "1000:1000"
    read_only: true
    tmpfs: ["/tmp"]
    cap_drop: [ALL]
    security_opt: [no-new-privileges:true]
    deploy:
      resources:
        limits: {cpus: "2.0", memory: 1G}
    volumes:
      - ./data:/app/data       # 仅 data 可写
```

## 删 AI CLI(⑧ 连带)

```dockerfile
# 删(⑧ Pydantic AI 通过 API 调用,不需 CLI)
# RUN bash -c 'set -o pipefail && curl -fsSL https://claude.ai/install.sh | bash -s -- 2.1.153'
# RUN npm install -g @openai/codex@0.129.0
```

- 镜像大瘦身 + 消除供应链风险(curl|bash 无校验)。
- 删 compose 的 claude/codex 凭据挂载(claude_settings/codex_config/codex_auth)。

## 前端构建(Vite 静态导出)

```dockerfile
FROM node:22-alpine AS node-build
COPY web/ .
RUN corepack enable && pnpm install --frozen-lockfile && pnpm build
# → dist/(Vite 默认输出,纯静态)

FROM python:3.13-alpine AS runtime
COPY --from=node-build /app/dist /app/web/dist   # 静态文件(非 standalone)
# 不需要 node 运行时
```

## Caddy 配置(加固)

```caddyfile
:5000 {
    encode gzip zstd

    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        # CSP(允许同源 + 内联样式,按需调)
        # HSTS 仅在 TLS 时开
    }

    handle /api/* {
        reverse_proxy 127.0.0.1:8000
    }

    handle {
        root * /app/web/dist
        try_files {path} /index.html    # 单回退规则覆盖所有前端路由
        file_server
    }
}
```

- 安全头 + encode + SPA try_files + API 反代。

## s6 服务

- `caddy`(longrun):依赖 `fastapi`(等 API 起来再 serve)。
- `fastapi`(longrun):`uvicorn progress.api.main:app --host 127.0.0.1 --port 8000`。
- `cron`(longrun):supercronic 按 `PROGRESS_SCHEDULE_CRON` 定时跑 `progress run`(与旧版一致,保证并行期运维心智零切换)。`PROGRESS_SCHEDULE_CRON` 为空时 `sleep infinity`(服务存活但不跑任务)。
- **删** nextjs s6 服务(Vite 产出静态文件,无 node server)。
- s6 v3 `dependencies.d/<dep>` 是空文件、文件名即依赖声明(s6-overlay 自身布局如此),`caddy/dependencies.d/fastapi` 正确标记 caddy 依赖 fastapi。

## `.dockerignore` 完善

排除:`web/dist`/`web/.next`(若有残留)/`web/node_modules`/`.local/`/`.zcode/`/`e2e/`/`docs/`/`.agents/`/`data/`/`__pycache__`/`specs/`。

## 删除陈旧副本 + 凭据 + 私有 registry

- 删 `src/progress/web/`(旧副本,① 定)。
- compose 删私有 registry `192.168.5.50:5000`(改公共镜像)。
- 删 claude/codex 凭据挂载。

## 构建依赖收敛

- **python-deps**:`uv export` + `uv pip install`(已有,正确)。
- **node-build**:`pnpm install --frozen-lockfile`(已有,正确)。
- **runtime 最小化**:git/curl/ca-certs/tzdata/github-cli(**无 node/npm**)。
- **uv 版本锁**:`pip install uv` 改固定版本或经 pyproject。

## OCI labels

```dockerfile
LABEL org.opencontainers.image.title="progress" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/..." \
      org.opencontainers.image.licenses="..."
```

## 删除清单

| 删除 | 理由 |
|---|---|
| claude/codex CLI 安装 | ⑧ Pydantic AI 替代 |
| nodejs/npm 运行时 | ⑬ Vite 静态 |
| nextjs s6 服务 | 无 node server |
| 根运行 | 非 root |
| 空 dependencies.d | 修启动顺序 |
| 私有 registry | 公共镜像 |
| claude/codex 凭据挂载 | ⑧ 连带 |
| 浮动 base tag + 无校验二进制 | digest + SHA256 |
