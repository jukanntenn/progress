# 可观测性上线手册（OpenTelemetry + Bugsink）

本手册指导如何在生产环境上线本次可观测性功能：OpenTelemetry traces/metrics 输出到容器内 `/app/data/telemetry/*.jsonl`（映射到宿主机 `./data/telemetry/`），错误/崩溃通过 `sentry-sdk` 上报到 Bugsink（`http://192.168.5.50:8770/`）。

- **回滚成本：低**。功能默认关闭，纯增量；下线只需翻转开关并重新部署，无数据迁移、无 DB schema 变更。
- **影响面**：仅新增 2 个遥测文件与到 Bugsink 的出站错误上报；不改变任何业务逻辑。
- 设计与实现记录见 [`observability.md`](./observability.md)，使用说明见 [`../guides/observability.md`](../guides/observability.md)。

---

## 0. 前置条件（Pre-flight）

| 项 | 要求 | 验证方式 |
|---|---|---|
| Bugsink 服务 | 已运行于 `http://192.168.5.50:8770/` | `curl -sS -o /dev/null -w '%{http_code}' http://192.168.5.50:8770/` → 期望 `302`（登录重定向） |
| Bugsink 项目 + DSN | 已在 Bugsink 创建项目并取得 DSN | 见 §1 |
| 生产主机 → Bugsink 网络 | 容器可直连 `192.168.5.50:8770`（同局域网，无需走 `192.168.5.101:7890` 代理） | 在**生产主机**上执行上面那条 curl |
| 镜像依赖 | 新镜像已包含 OTel/sentry-sdk 依赖 | 见 §3 构建步骤（Dockerfile 在构建时从 `uv.lock` 重新生成 requirements） |
| Ansible Vault | 持有 `~/.ansible-vault/progress.pwd` | 见 §2 |

> 提示：验收阶段已用 DSN `http://98f360b91ad9474d9144c44327913cf0@192.168.5.50:8770/2`（project_id=2）验证过端到端投递（HTTP 200）。生产可直接复用该项目，或新建独立项目。

---

## 1. 准备 Bugsink 项目与 DSN

1. 浏览器打开 `http://192.168.5.50:8770/`，登录。
2. 进入（或新建）目标项目 → Project Settings，复制 **DSN**，形如：
   ```
   http://<public-key>@192.168.5.50:8770/<project-id>
   ```
   记下完整 DSN（含公钥与 project-id），后续作为 secret 注入。
3. （可选）清理验收期间遗留的测试事件：在 project 2 中 resolve/delete 以下 event_id：
   `58210c809fdf426d8b28f5d262e2cb0d`、`98db4309a3b34feab782f3081fe1084b`、`db107e65b17546d9873aa0e825e90e43`、`c9fd1ee92ea3451d948954fd94756ce0`、`e5e9f9ba69a14d8eb9eee53ab729ae22`、`3fd42583bdd242b2a347946ac4b4e03c`。

---

## 2. 注入配置（Ansible 管理）

生产配置由 Ansible 渲染。DSN 是 secret，按本项目惯例放入 vault，并在 compose 模板中以环境变量引用。

> 推荐用**环境变量**启用（DSN 不落配置文件、由 vault 管理、Ansible 全权托管）。`[observability]` 是**基础设施**配置，每次启动都会重新读取，因此无需 `progress config import`。

### 2.1 把 DSN 写入 Vault

```bash
ansible-vault edit devops/ansible/vars/vault_main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```

新增一行（与现有 `gh_token`、`feishu_webhook_url` 等 secret 并列）：

```yaml
bugsink_dsn: "http://<public-key>@192.168.5.50:8770/<project-id>"
```

### 2.2 在 compose 模板中启用

编辑 `devops/ansible/templates/docker-compose.yml.j2`，在 `environment:` 下追加：

```jinja
    environment:
      - PROGRESS_SCHEDULE_CRON=30 8,22 * * *
      # —— 可观测性（新增）——
      - PROGRESS_OBSERVABILITY__OTEL__ENABLED=true
      - PROGRESS_OBSERVABILITY__OTEL__EXPORT_DIR=/app/data/telemetry
      - PROGRESS_OBSERVABILITY__BUGSINK__DSN={{ bugsink_dsn }}
      - PROGRESS_OBSERVABILITY__BUGSINK__ENVIRONMENT=prod
```

- 只想先开 OTel、暂不上报 Bugsink：只保留前两行（`OTEL__*`），删去 `BUGSINK__*`。
- `EXPORT_DIR` 必须落在已挂载的 `./data` 卷内（即容器内 `/app/data/...`），否则文件会写进容器临时层、重启即丢。

### 2.3（可选）改走 config.toml

由于 `main.yml` 中 "Copy config.toml" 任务被注释，宿主机上的 `config.toml` 不会被覆盖。也可直接编辑生产机上的 `./config.toml` 追加：

```toml
[observability.otel]
enabled = true
export_dir = "data/telemetry"

[observability.bugsink]
dsn = "http://<public-key>@192.168.5.50:8770/<project-id>"
environment = "prod"
```

> 建议优先用 §2.1/2.2 的 env+vault 方式（DSN 不进文件）。本节仅作备选。

提交代码与模板改动后进入构建。

---

## 3. 构建并推送镜像

```bash
# 多架构构建并推送到 192.168.5.50:5000
python docker/build.py --push
```

确认推送成功（镜像 `192.168.5.50:5000/progress:latest` 已更新）。Dockerfile 会在构建阶段执行 `uv export …`，新依赖（opentelemetry-*、sentry-sdk）随之固化进镜像。

---

## 4. 部署到生产

```bash
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```

playbook 会：渲染 compose → `pull: always` 拉取新镜像 → 重建容器。容器内 s6-overlay 自动拉起 fastapi（长驻）、cron（supercronic，按 `30 8,22 * * *` 运行 `progress check`）等服务。

---

## 5. 上线后验证（Post-deploy）

> 容器名 `progress`；下文 `docker compose` 在生产机的 `~/docker/progress/`（即 `app_path`）下执行。

### 5.1 启动日志确认初始化成功
```bash
docker compose logs app 2>&1 | grep -iE "Bugsink error reporting enabled|telemetry"
```
期望看到 `Bugsink error reporting enabled (environment=prod)`。无报错即 `sentry-sdk` 初始化成功。

### 5.2 遥测文件已生成
```bash
# API 服务（长驻）会持续写 traces（HTTP/DB span）
docker exec progress ls -la /app/data/telemetry/
```
期望出现 `traces.jsonl`、`metrics.jsonl`。也可在宿主机查看 `./data/telemetry/`。

### 5.3 触发一次 check，验证业务链路 span
```bash
# 手动跑一次 check（与 cron 同路径），随后检查 traces
docker exec progress progress --config /app/config.toml check
docker exec progress sh -c "tail -n 3 /app/data/telemetry/traces.jsonl"
```
期望看到 `progress.check`、`repo.sync`、`repo.analyze`、`ai.call` 等 span，且 `repo.sync`/`ai.call` 的 `parent_id` 指向 `progress.check`。

### 5.4 指标文件
```bash
docker exec progress tail -n 1 /app/data/telemetry/metrics.jsonl | python3 -m json.tool
```
期望包含 `progress.repos.checked`、`progress.analysis.duration` 等指标。

### 5.5 日志 trace 关联
```bash
docker exec progress tail -n 20 /app/data/progress.log
```
期望每行带 `[trace_id=0x… span_id=0x…]`（关闭态则为空，属正常）。

### 5.6 Bugsink 收到事件
- 等待一次真实的 check 报错（若有），或临时制造一个：在容器内 `python -c "import sentry_sdk; ..."` 仅限排障；
- 更稳妥：到 Bugsink 项目页查看是否出现新 issue；本次验收已用独立 envelope 与 sentry-sdk 两条路径确认 HTTP 200。

---

## 6. 运维注意事项

### 6.1 ⚠️ 文件保留（生产必读）
当前遥测文件为**追加写、无内置轮转**，100% 采样下会**无限增长**。生产上线**必须**配置轮转，否则磁盘会被写满。

推荐在生产机上用 `logrotate` 的 `copytruncate`（导出器持有文件句柄追加写，`copytruncate` 可在不重启进程的前提下切割）：

新增 `/etc/logrotate.d/progress-telemetry`：
```
/path/to/data/telemetry/*.jsonl {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
    size 100M
}
```
（把路径替换为生产机上的实际 `data/telemetry` 绝对路径。）日常按 100M 或每日切割，保留 14 份压缩归档。

### 6.2 文件位置
- 容器内：`/app/data/telemetry/{traces,metrics}.jsonl`
- 宿主机：`<app_path>/data/telemetry/`（即 `./data/telemetry/`）
- 人工/AI 检索：见 [`../guides/observability.md`](../guides/observability.md) 的 jq 示例。

### 6.3 性能与配额
- 100% 采样，内部低流量工具，开销可忽略；CLI（短驻）用同步 processor，API（长驻）批量导出。
- Bugsink 配额：每项目默认保留 10000 事件、5 分钟/小时/月有上限，超限返回 HTTP 429（客户端自动退避）。本项目错误量低，一般不会触达。

---

## 7. 回滚 / 关闭

任选其一，**无需回滚镜像**（功能默认关闭，老镜像忽略这些 env 即可）：

**A. 仅关闭（保留镜像）**：编辑 `docker-compose.yml.j2`，将 `PROGRESS_OBSERVABILITY__OTEL__ENABLED` 改为 `false`、删除（或留空）`PROGRESS_OBSERVABILITY__BUGSINK__DSN`，重跑 §4 部署。重启后不写文件、不联网。
**B. 完全回滚**：部署上一版镜像（`python docker/build.py` 旧 tag 或镜像仓库回退）并移除上述 env。

回滚后已写入的 `*.jsonl` 与 Bugsink 中已入库的事件保留，不影响业务。

---

## 8. 故障排查

| 现象 | 排查 |
|---|---|
| `data/telemetry/` 无文件 | 确认 `PROGRESS_OBSERVABILITY__OTEL__ENABLED=true`；确认 `EXPORT_DIR` 在挂载卷内；`docker compose logs app` 查看是否有 instrumentation 警告 |
| traces.jsonl 为空 / span 缺失 | API 路径：发一个 HTTP 请求即可生成；CLI 路径：需等 cron 或手动 `progress check`（短驻进程在退出时 `force_flush`） |
| Bugsink 收不到事件 | 在生产机 `curl` 验证连通；确认 DSN 公钥与 project-id 正确；查 Bugsink 是否返回 429（配额）；查 `progress.log` 是否有 `Bugsink initialization failed` |
| 日志里 `trace_id=` 为空 | 正常——表示当前不在 span 上下文中或 OTel 未启用；确认 `otel.enabled=true` 后在 check 运行期间应有值 |
| 磁盘占用增长快 | 见 §6.1，配置 logrotate |

---

## 9. 上线签字清单（Sign-off）

- [ ] §0 前置条件全部满足（Bugsink 可达、vault 就绪）
- [ ] §1 DSN 已取得并记入 vault（`bugsink_dsn`）
- [ ] §2 compose 模板已加 env，代码/模板改动已提交
- [ ] §3 镜像已 `--push` 成功
- [ ] §4 Ansible 部署完成、容器已重建
- [ ] §5.1 启动日志出现 `Bugsink error reporting enabled`
- [ ] §5.2 遥测文件已生成
- [ ] §5.3 一次 check 后 traces 含完整 span 树
- [ ] §5.6 Bugsink 收到事件
- [ ] §6.1 logrotate（或等效轮转）已配置
- [ ] §7 已知悉回滚步骤
