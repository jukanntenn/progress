# 部署指南

[English](deployment.md) | 中文

Progress 以单个加固容器交付：Caddy 托管静态 Vite SPA、FastAPI 后端与 supercronic 调度器，全部由 s6-overlay 监管。本指南覆盖 Docker 部署，以及从旧版（redesign 前）构建的一次性迁移。

## Docker 快速上手

### Docker Compose（推荐）

1. 拉取或构建镜像（见[构建镜像](#building-the-image)）。

2. 创建一个最小的 `config.toml`（Ansible 级）。它只承载数据根目录，其余设置全部存放在数据库中并通过 Web UI 编辑：

   ```toml
   state_home = "/app/data"
   ```

3. 创建 `docker-compose.yml`：

   ```yaml
   services:
     progress:
      image: progress:latest
      container_name: progress
      ports:
        - "5000:5000"
      read_only: true
      tmpfs:
        - /tmp
      cap_drop:
        - ALL
      security_opt:
        - no-new-privileges:true
      volumes:
        - ./config.toml:/app/config.toml:ro
        - ./data:/app/data
      environment:
        # supercronic reads this to schedule periodic pipeline runs.
        # Empty/unset => the cron service idles (no scheduled runs).
        - PROGRESS_SCHEDULE_CRON=0 8 * * *     # daily at 08:00
      healthcheck:
        test: ["CMD", "curl", "-fsS", "http://127.0.0.1:5000/healthz"]
        interval: 30s
        timeout: 5s
        retries: 3
        start_period: 30s
      restart: always
   ```

   `data/` 目录必须可被容器内的非 root 用户 `progress` 写入：请相应设置宿主机目录的属主或权限（`chown 1000:1000 ./data` 或 `chmod 777 ./data`）。

4. 启动容器：

   ```bash
   docker compose up -d
   docker compose logs -f
   ```

   首次启动约需 15 秒（建库 + 迁移 + 可观测性初始化）；之后重启更快。在 `http://<your-host>:5000` 打开 Web UI。

### 单容器

仅用于快速体验；长期部署请使用 Docker Compose。

```bash
mkdir -p data && chown 1000:1000 data
docker run -d \
  --name progress \
  -p 5000:5000 \
  -e PROGRESS_SCHEDULE_CRON="0 8 * * *" \
  -v "$PWD/config.toml:/app/config.toml:ro" \
  -v "$PWD/data:/app/data" \
  progress:latest
```

## 容器架构

Progress 以单个非 root 容器运行，内部由 [s6-overlay](https://github.com/just-containers/s6-overlay) 托管三个服务：

- **Caddy**：监听 `5000` 端口的反向代理 + 静态 SPA 服务器（外部入口）
- **FastAPI**：位于 `127.0.0.1:8000` 的后端 API（内部）
- **Cron**：按 `PROGRESS_SCHEDULE_CRON` 运行 `progress run` 的 [supercronic](https://github.com/aptible/supercronic) 调度器

```text
                    ┌───────────────────────────────────────────────┐
                    │           progress container (:5000)          │
                    │                                               │
  External ────────►│  Caddy (0.0.0.0:5000)                        │
  :5000             │    ├ /api/v1/*   ──► FastAPI (127.0.0.1:8000) │
                    │    ├ /healthz    ──► FastAPI                  │
                    │    ├ /readyz     ──► FastAPI                  │
                    │    └ rest        ──► Vite SPA (static dist/)  │
                    │                                               │
                    │  supercronic ──► progress run (on schedule)   │
                    │                                               │
                    │  s6-overlay manages: caddy, fastapi, cron     │
                    └───────────────────────────────────────────────┘
```

Caddy 负责 TLS 终止、安全响应头与请求路由（见 `docker/Caddyfile`）。`/healthz` 与 `/readyz` 探针被反向代理到 FastAPI（而非作为 SPA 回退提供），因此 Docker 的 `HEALTHCHECK` 反映的是真实的后端健康状态；`/readyz` 还会额外 ping 数据库。

## 定时运行

流水线按 `PROGRESS_SCHEDULE_CRON` 定义的调度运行：

```bash
PROGRESS_SCHEDULE_CRON="0 8 * * *"     # daily at 08:00
```

- **已设置时**：supercronic 按 cron 调度运行 `progress run -c /app/config.toml`。该服务**不会**在启动时立即运行一次（避免与旧版构建并行运行时出现重复执行）。
- **未设置时**：cron 服务空转（`sleep infinity`）。手动触发一次运行：

  ```bash
  docker compose exec progress progress run -c /app/config.toml
  ```

cron 表达式遵循标准的 5 字段语法：

```text
┌───────────── Minute (0 - 59)
│ ┌───────────── Hour (0 - 23)
│ │ ┌───────────── Day of month (1 - 31)
│ │ │ ┌───────────── Month (1 - 12)
│ │ │ │ ┌───────────── Day of week (0 - 7, Sunday = 0 or 7)
│ │ │ │ │
* * * * *
```

## AI 分析

Progress 使用 [Pydantic AI](https://ai.pydantic.dev/) 做 diff 分析。首次启动后通过 Web UI（`/config` → `core.analysis`）或配置 API 进行配置，它**不**通过 `config.toml` 或环境变量设置：

- `provider` + `model`：Pydantic AI 的模型字符串，例如 `model = "anthropic:claude-sonnet-4"`。
- `api_key`：提供商 API key（以 `SecretStr` 存储）。
- `base_url`：可选，用于 OpenAI 兼容的自托管端点。
- `language`：分析结果的输出语言。
- `concurrency`：每个集成的分析并行度。

`provider`/`api_key` 为空时，AI（人工智能）分析被禁用，diff 退回截断处理。没有内置的 CLI 提供商：分析只走 Pydantic AI 的 API 路径。

## 配置

应用配置存放在**数据库**的 `config` 表中，按分区（`core`、`repo`、`changelog`、`proposal`、`feed`）划分。`config.toml` 属 Ansible 级，**只**承载 `state_home`；其余全部在运行时编辑：

- 日常设置通过 Web UI（`/config`）或 API（`PUT /api/v1/config/{section}`）编辑。Web UI 依据服务端的 JSON Schema 经 RJSF 渲染配置表单，secret 字段在浏览器中以 `type="password"` 输入框遮蔽。写入会用该分区的 Pydantic 模型校验：非法载荷返回 422，数据库保持原状。
- 容器启动时，在数据库迁移之后，`migrate_config_data()` 会修复旧编辑器留下的已知坏结构（例如 `core.observability.bugsink` 被存成列表、`recipient` 含非字符串条目），使运行时无需回退默认值即可加载配置。该操作幂等：健康数据从不被改动。
- 首次部署或测试时，在 `config.toml` 旁边放置 `config.db.toml` 种子文件，启动时会导入数据库（数据库值优先于种子）。生产环境务必确保不存在 `config.db.toml`：数据库是唯一真源。

环境变量覆盖（`PROGRESS_` 前缀，`__` 表示嵌套键）仍然生效，但只对数据库尚未设置的键有效。生产部署更应通过 Web UI 编辑而非使用环境变量。注意：`core.observability.otel.*` 不是配置字段（OTel 导出路径由 `state_home` 推导）：**不要**设置 `PROGRESS_OBSERVABILITY__OTEL__*` 环境变量，否则会未通过 `CoreConfig` 校验并阻止启动。

## 数据与数据库

Progress 把所有数据存放在单一数据目录下（容器内 `/app/data`，即 `state_home`）：

- `progress.db`：SQLite 数据库（报告、仓库/owner/changelog/proposal 状态、`config` 表）
- `repos/`：已克隆的受跟踪仓库
- `logs/`：应用日志
- `observability/`：OpenTelemetry traces/metrics JSONL

SQLite（WAL 模式）是唯一的数据库后端。保持 `data/` 卷持久化：

```yaml
volumes:
  - ./data:/app/data
```

## 从旧版构建迁移

此次重构改变了数据库模式（peewee → tortoise-orm）与配置存储模型（单个 `app_config` blob → 按分区的 `config` 行）。一个一次性迁移脚本无损地搬移全部状态表与配置：

```bash
# On the new server, with the legacy DB copied to ./old/progress.db:
uv run python scripts/migrate_from_legacy.py \
  --old ./old/progress.db \
  --new ./data/progress.db
```

脚本拒绝覆盖已含数据的新数据库。它会迁移：

- **状态表**逐字迁移（repositories、reports、batches、owners、changelog/proposal tracker、proposals），并将 `batch` 改名为 `batches`、`proposal_trackers` 改名为 `proposal_tracker_states`。
- **配置**从旧版 `app_config.data` JSON blob 迁入 `core` / `repo` / `changelog` / `proposal` 分区，丢弃新模式中没有的字段（如 feishu 的 `timeout`），`analysis` 留空（经 Web UI 填写）。secret（gh_token、webhook URL）以明文保留，与配置表的存储方式一致。

`repo` 分区从 `repositories`/`github_owners` 表填充，使 tracker 的 reconcile 过程不会在首次运行时把迁移来的检查点当垃圾回收。请**务必**在第一次定时 `progress run` 之前执行迁移。

## 反向代理

部署在外部反向代理之后时，将流量转发到 `5000` 端口：

```caddyfile
progress.example.com {
    reverse_proxy localhost:5000
}
```

如果 Progress 挂在公开 URL 之下，请设置 `core.web.base_url`（经 Web UI 或配置 API），使超长报告能链接回完整报告。

<a id="building-the-image"></a>

## 构建镜像

```bash
uv run python docker/build.py                                        # build for the local platform (load), tag :main
uv run python docker/build.py --push --all-platforms                # build + push multi-platform (default registry)
uv run python docker/build.py --push --registry ghcr                # build + push (alias)
uv run python docker/build.py --platform amd64                      # build a specific platform
uv run python docker/build.py --tags v1.0.0 20260813                # additional tags (main always included, deduplicated)
uv run python docker/build.py --no-cache                            # full rebuild, no layer reuse
```

- **标签**：始终包含 `main`（内部滚动 tag）；`--tags` 追加更多标签并去重。
- **git_sha 注入**：每次构建都把当前 `git rev-parse HEAD` 作为 `GIT_SHA` 构建参数传入；运行时经 `/api/v1/version` 暴露该值，部署自动化用它与发布的 commit 比对，确认新镜像确实已上线。
- registry 目标：别名 `ghcr` → `ghcr.io`，`dockerhub`/`docker` → `docker.io`；也可以是任意主机，如 `registry.local:5000`（使用别名时 owner 从 git remote 自动推导）。
- CI **不**使用此脚本：GitHub Actions 用官方的 `docker/login-action` + `docker/metadata-action` + `docker/build-push-action` 构建（见 `release.yml`）。本脚本是本地构建工具：注册 QEMU binfmt 后由 buildx 完成跨平台构建。
- 第三方二进制（Caddy、s6-overlay、supercronic）下载时强制校验 SHA checksum。
- 运行 `uv run python docker/build.py --help` 查看全部选项。

## Ansible 自动化

`devops/ansible/` 下有一套自动部署 playbook：从模板渲染 `config.toml` 与 `docker-compose.yml`，拉取镜像、启动容器，再从控制机验证健康。它在项目根目录**和** `devops/ansible/` 下都能运行：根 `ansible.cfg` 与目录内那份指向同一组文件。

secret 以单个 `!vault` 变量加密，按环境分存在 `devops/ansible/group_vars/<env>/vault.yml`（按 group 自动加载）。每个环境在 **avpm keyring** 中有自己的 vault 密码：`progress-prod` 守护 `prod` 组（`fn`），`progress-test` 守护 `staging` 组（`oect`），经 `ansible.cfg` 中的 `vault_identity_list = progress-test@~/.local/bin/avpm-client, progress-prod@~/.local/bin/avpm-client` 接入（ansible 以 `avpm --vault-id <label>` 调用 avpm 客户端脚本；先尝试匹配的密码，再按序尝试其余密码）。加密一个值：

```bash
ansible-vault encrypt_string --vault-id progress-test@~/.local/bin/avpm-client \
  --stdin-name <name> >> devops/ansible/group_vars/staging/vault.yml
```

每个会话运行一次 `avpm unlock`；若缺失，执行部署的 agent 会提示你。用 `uv run python scripts/vault.py`（`set` / `get` / `list` / `check` / `remove`）管理按变量的 vault 块；`check` 会在各自 vault-id 下对每个环境的每个变量做解密验证，且不打印值。

```bash
ansible-playbook devops/ansible/main.yml                             # deploy staging (oect) — default
ansible-playbook devops/ansible/main.yml -e target=prod              # deploy production (fn)
ansible-playbook devops/ansible/main.yml -e verify_sha=no            # deploy without the git_sha gate
```

**部署后验证**（在控制机上运行 `scripts/check_deploy.py`）：先等待 `/readyz`（应用已起 + 数据库可达），再将 `/api/v1/version` 报告的已部署 `git_sha` 与本地 HEAD 比对。不一致则 playbook 失败：容器在跑并不能证明新镜像已上线。

staging（`oect`，arm64）从内网 registry `192.168.5.50:5000`（就托管在 oect 机器上）拉取滚动 `:main` tag。它的调度器交付时为空转状态（`cron: ""`，手动触发运行）；只要还有 `__FILL_ME__` 占位符未填（`group_vars/staging/env.yml` 的 `host_port`/`health_url`、`host_vars/oect.yml` 的 `home`），playbook 就拒绝部署。为 staging 验证发一个新构建：

```bash
uv run python docker/build.py --push --all-platforms   # 1. build + push :main (amd64 + arm64)
ansible-playbook devops/ansible/main.yml               # 2. deploy + verify on oect
```

生产（`fn`）用同样两条命令加 `-e target=prod` 执行：这是刻意保留的一步，仅在构建通过 staging 验收之后进行。为下一轮 staging 验证发布更新的 `:main` 不会动正在运行的 `fn` 容器；它只在下一次显式生产部署时才变化。

Inventory（主机清单）：`staging` 组 = `oect`（验证，arm64）；`prod` 组 = `fn`（生产）。外部用户需将 `group_vars/` 与 `host_vars/`（含各环境的 `vault.yml`）替换为自己的值。

每次升级后，确认数据库自动迁移成功：启动迁移从不因模式错误崩溃（只记录 `migration_failed` 指标并降级），所以要检查 `data/observability/metrics.jsonl` 与 `data/logs/progress.log`，而不是只看容器是否在运行。
