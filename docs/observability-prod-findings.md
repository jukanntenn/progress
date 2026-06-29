# 生产部署检查发现与后续改进项

可观测性功能（OpenTelemetry traces/metrics → 本地 JSON-Lines，错误 → Bugsink）的生产运行情况记录。本文随每次复查更新：首次上线检查 **2026-06-28**，最近一次复查 **2026-06-29**。可观测性功能本身**已验证正常工作**；本文记录需要后续处理的运维风险与改进建议。

> **2026-06-29 代码修复**：问题 1（可见性）、问题 4、问题 5 的根因已在代码中修复并补单测（483 项全绿），**待部署到生产后复查闭环**。详见各问题小节的"修复"段与文末待办清单。

- 上线手册：[`observability-deploy.md`](./observability-deploy.md)
- 设计/实现/验收记录：[`observability.md`](./observability.md)
- 使用指南：[`../guides/observability.md`](../guides/observability.md)

**检查环境**：生产主机 `alice@192.168.5.50`（armbian / arm64），容器 `progress`，镜像 `192.168.5.50:5000/progress:latest`，数据卷 `/mnt/ssd/alice/docker/progress/data`。容器当前实例 `StartedAt = 2026-06-28 16:49 CST`（部署当天发生过一次容器重建；当天 10:28 的首次检查来自前一实例），至 06-29 09:14 CST 检查时已稳定运行约 16h。

---

## 已验证正常（无需处理）

- 新代码在镜像中（`import progress.telemetry` / `sentry_sdk` / `opentelemetry` OK）。
- 环境变量注入正确：`OTEL__ENABLED=true`、`EXPORT_DIR=/app/data/telemetry`、`BUGSINK__DSN=<已设>`、`ENVIRONMENT=prod`。
- Bugsink 初始化成功——06-28~06-29 共 4 次进程启动均见 `Bugsink error reporting enabled (environment=prod)`。
- `traces.jsonl` / `metrics.jsonl` 持续正常生成，全部为有效单行 JSON。
- Span 树正确：每次 `progress.check`（`repo_count=18`）下嵌套 `repo.sync` / `repo.analyze` / `ai.call`，并发（线程池）下 context 传播正确。
- 自动埋点生效：出站 HTTP（`GET`/`POST`）、DB（`SELECT`/`PRAGMA`/`CREATE`/`UPDATE`/`INSERT`，peewee→sqlite3）。
- 业务指标 `progress.repos.checked` / `analysis.duration` / `reports.generated` / `notifications.sent` 均已记录。
- `progress.log` 行携带真实 `trace_id` / `span_id`（日志关联生效）。
- ✅ **（06-29 复查）** 上次"本轮无新提交故无 AI span"的观察已闭环：近两天出现 `ai.call`×13、`repo.analyze`×7，关键瓶颈 span 已在生产被真正演练。

---

## 🔴 问题 1（高风险）：AI 分析超时把单任务拖到 ~15 分钟，且对 Bugsink 不可见

> 06-29 复查新发现。目前最显著的运行问题。

**证据**
- 06-28 22:30 CST 的 cron 运行耗时 **26.5 分钟**（其余三次分别为 7.4 / 10.8 / 9.4 分钟），明显异常。
- 根因：某仓库 release（v1.5.0）的 `claude` CLI 分析超时，触发 3 次重试、每次撞 300s 超时，日志链条完整：
  - `Command failed (attempt 1/3), retrying in 5s. Error: AI tool 'claude' timed out after 300s`
  - `attempt 2/3, retrying in 10s … timed out after 300s`
  - `Failed to analyze release v1.5.0: … timed out after 300s`
  - ERROR `Command failed, max retries (3) reached`
  - ERROR `AI tool 'claude' unavailable after 3 attempt(s) (last exit code None): Command '['claude', '-p', '']' timed out after 300 seconds`
- 唯一的 `ai.call` ERROR span 持续 **916.7s**（≈ 3×300s，含重试退避，重试循环在同一 span 内）；其余 12 次 `ai.call` 正常，耗时 8~32s。
- `progress.analysis.failures` 指标记录 1 次（`reason=transient`）。

**两个隐患**
1. **失败被吞，Bugsink 收不到**：超时被 `try/except` 捕获并降级为日志，无未处理异常 → 不上报 Bugsink。与"被吞失败不可见"的设计盲区一致，本次已被真实触发。
2. **重试 × 长超时代价高**：单次分析最坏 ~15 分钟（3×300s），直接把整轮 cron 拉长到 26.5 分钟；多仓库同时超时会进一步放大。

**建议**
- 对"重试耗尽"的 AI 失败显式 `sentry_sdk.capture_exception()`，让 Bugsink 看到它（同时覆盖问题 4 的盲区）。
- 评估降低 `claude` 单次 timeout、或改用流式/异步调用，避免"重试 × 长超时"叠加。

**修复（2026-06-29，代码已提交，待部署复查）**
- ✅ 第一条已实现：在 `telemetry.py` 新增 `report_error(exc, **tags)` 助手（未启用时 no-op；启用时 `push_scope` 打标签后 `sentry_sdk.capture_exception()`），并在 release 分析失败处（`contrib/repo/repository.py` 的 `_analyze_all_releases` except）显式上报，附带 `repo/provider/release_tag/stage` 标签。错误路径用 `getattr(analyzer, "provider", "unknown")` 防御，避免二次异常吞掉原始错误。
- ⏳ 第二条（300s×3 超时/重试调优）暂缓，单列为后续任务（独立的性能权衡，需评估对分析质量的影响）。

---

## 🟠 问题 2（运维风险）：遥测无轮转，`metrics.jsonl` 已超 traces 成为增长主力

> 原"问题 1"。06-29 复查：磁盘危机缓解，但轮转仍未配，且增长主力从 traces 转向 metrics。

**证据**
- `/etc/logrotate.d/` 下**仍无** progress/telemetry 条目——上线手册 §6.1 的 logrotate 缓解**仍未应用**。
- ✅ 磁盘水位从 06-28 的 **95%（可用 5.6G）回落到 60%（可用 43G）**，有人清理了约 37G，短期危机解除。数据卷大头 `data/repos` 3.1G、`progress.db`+`.bak` 59M，均正常。
- ❌ 但遥测约 1 天涨了 4 倍：traces 697→**2900 行 / 2.37M**，metrics 91→**655 行 / 3.05M**——**`metrics.jsonl` 反而更大**。
- 增长来源：`http.client.duration`（出站 HTTP 自动指标）出现在**全部 655 次导出**中——API 长驻进程每 60s 把累积直方图全量重导一遍，且随 URL/路由属性组合增多而膨胀。这是无界、持续型增长（不像 CLI 是脉冲型）。

**建议**
1. 立即配置 logrotate（导出器持有句柄追加写，须用 `copytruncate`），**traces 与 metrics 都要覆盖**。新建 `/etc/logrotate.d/progress-telemetry`：
   ```
   /mnt/ssd/alice/docker/progress/data/telemetry/*.jsonl {
       daily
       rotate 14
       compress
       missingok
       notifempty
       copytruncate
       size 100M
   }
   ```
2. 收敛 metrics 增长：调大 API 的导出间隔，或对 `http.client.*` 收敛属性基数/过滤（与问题 3 联动），否则 metrics 会比 traces 更先吃磁盘。

---

## 🟡 问题 3（建议改进）：traces.jsonl 被出站 HTTP span 淹没

> 原"问题 2"。06-29 复查：仍未处理，比例不变。

**证据**：Span 分布 `GET`(2394，占 82.5%) ≫ DB(404) ≫ `repo.sync`(72) ≫ `ai.call`(13) ≫ `repo.analyze`(7) ≫ `progress.check`(4)。业务 span 合计 <4%，被淹没；并放大磁盘增长（呼应问题 2）。

**可选方案**（未变）
- A. 关闭 `requests` 自动埋点（最省事，牺牲出站 HTTP 可见性）。
- B. 加 span/metric 过滤器，丢弃 `http.client.*` span（**推荐**，同时缓解问题 2 的 metrics 膨胀）。
- C. 维持现状，仅靠 logrotate 控制体积。

---

## 🟡 问题 4（新发现）：AI 输出非法 JSON，分析静默失败（指标盲区）

> 06-29 复查新发现。

**证据**（近两天 WARNING）：
- `Code analysis failed: Could not extract JSON from Claude output`
- `Code analysis failed: Expecting ',' delimiter: line 2 column 52`
- `Code analysis failed: Expecting ',' delimiter: line 2 column 28`

`claude` 返回非法 JSON，解析失败导致对应分析无产出。被捕获为 WARNING，**未计入 `progress.analysis.failures`**（不同代码路径），存在指标盲区。

**建议**：解析失败时显式记录 `analysis.failures` 指标 + `sentry_sdk.capture_exception()`；或加 JSON 修复/重试。

**修复（2026-06-29，代码已提交，待部署复查）**：✅ 已实现，同时补上指标盲区与 Bugsink 上报。在 code-diff（`contrib/repo/analysis.py:analyze_diff`）与 proposal（`contrib/proposal/analysis.py:run_analysis`）两条 JSON 解析失败路径上：新增 `telemetry.record_analysis_failure(provider, reason="parse")`（仅增计数器、不重复记时长——因为 `run_tool` 此时已记 `ok=True` 的时长），并调用 `report_error()` 上报 Bugsink。release 超时路径的指标仍由 `run_tool` 记 `reason=transient`，不重复计数。

---

## 🟡 问题 5（业务，非可观测性）：`erc` proposal tracker 克隆持续失败

> 原"附带观察"。06-29 复查：仍每次失败，升级为独立项。

**证据**：近两天 **5 条 WARNING**，06-28 22:46 与 06-29 08:31 均复现：
`git clone https://github.com/ethereum/ercs … returned non-zero exit status 128`
被 `try/except` 吞为 WARNING，不影响主流程，但 erc tracker 实际从未成功。

**建议**：排查 `ethereum/ercs` clone exit 128（仓库路径/网络/代理）；若希望这类失败进 Bugsink，在 `except` 中显式 `sentry_sdk.capture_exception()`。

**修复（2026-06-29，代码已提交，待部署复查）**：✅ 根因定位并修复。`git ls-remote --heads https://github.com/ethereum/ercs` 确认该仓库默认分支是 **`master`**（无 `refs/heads/main`），而 `KIND_CONFIGS[ProposalKind.ERC].branch` 误配为 `"main"` → `git clone --single-branch --branch main` 以 exit 128 失败。已改为 `"master"`（与 EIPs 一致）。同时按问题 1/4 的理念，在 proposal tracker 的 clone 失败（`GitException`）处加 `report_error(e, kind=..., stage="clone")` 并 re-raise，保持原有 WARNING 行为的同时让这类失败进 Bugsink。

---

## 🔵 其它观察（近两天，无需紧急处理）

- **容器重建一次**：06-28 16:49 CST（`StartedAt`），此后稳定；原因未明（手动重部署或自动重启），可留意。
- **uTools changelog 抓取瞬时失败 1 次**：`www.u-tools.cn` ConnectionReset（06-28 16:51），随后一次返回 200，属瞬时。
- `apache/airflow` diff 355443 字符超 200000 上限被截断（预期行为）。
- `progress.log` 4.5M / 38858 行，跨 04-28~06-29（约 2 个月），尚未触发 5M 轮转；近两天 ERROR 仅 2 行（均为问题 1 的重试耗尽）、WARNING 13 行。
- Caddy 的 `HTTP/2/3 skipped (requires TLS)`、s6 的 `process reaping disabled` WARNING 均为既有现象，与本次无关。

---

## Bugsink 投递确认状态

- 初始化成功（4 次进程均见 INFO）；容器内 `192.168.5.50:8770` 可达。
- **按设计只有未处理异常才上报**；本次所有失败（问题 1/4/5）均被 `try/except` 捕获 → **Bugsink 预期 0 事件**。这恰好印证了"被吞失败不可见"的盲区。
- 读侧（项目内事件列表）需登录 Bugsink 验证，本次未做。如需端到端确认，可主动发一条测试事件。

---

## 后续待办清单（2026-06-29 刷新）

按优先级排序：

- [x] **问题 1**：给"重试耗尽"的 AI 失败加 `sentry_sdk.capture_exception()`（同时覆盖问题 4 的盲区）→ 已实现 `report_error()` 助手并在 release 分析失败处上报
- [ ] **问题 1**：审视 `claude` 的 300s×3 重试/超时组合（降单次 timeout，或改流式/异步调用）→ 暂缓，单列后续
- [ ] **问题 2**：配置 logrotate（`copytruncate`，traces **和** metrics 都覆盖）
- [ ] **问题 2/3**：收敛 metrics 增长——过滤/收敛 `http.client.*`（方案 B，一举两得）
- [x] **问题 4**：AI JSON 解析失败时记录指标 + 上报；或加 JSON 修复/重试 → 已实现 `record_analysis_failure(reason="parse")` + `report_error()`（code-diff 与 proposal 两条路径）
- [x] **问题 5**：排查 `ethereum/ercs` clone exit 128 → 根因是默认分支误配（`main`→`master`），已修复；并在 clone 失败处加 `report_error()`
- [ ] （可选）主动发一条测试事件，验证 Bugsink 端到端入库
- [x] ~~（旧问题 3）等有新提交的 cron 运行后复查 `ai.call` / `repo.analyze` / `analysis.duration`~~ → 06-29 已确认出现，闭环
- [x] ~~（旧问题 1）处理磁盘水位 95%~~ → 已回落到 60%（清理约 37G）；但 logrotate 仍未配，见问题 2
