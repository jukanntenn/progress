# Observability rollout runbook (OpenTelemetry + Bugsink)

English | [中文](observability-deploy.zh.md)

This runbook covers bringing the observability feature to production: OpenTelemetry traces/metrics are written to `/app/data/observability/*.jsonl` inside the container (mapped to `./data/observability/` on the host), and errors/crashes are reported to Bugsink (`http://192.168.5.50:8770/`) via `sentry-sdk`.

- **Rollback cost: low.** OTel traces/metrics are always on (a code constant, no switch); Bugsink is driven by its DSN — clear it and reporting stops.
- **Blast radius**: two new telemetry files plus outbound error reporting to Bugsink; no business logic changes.
- Design and implementation notes live in [`observability.md`](./observability.md).

---

## 0. Pre-flight

| Item | Requirement | How to verify |
|---|---|---|
| Bugsink service | Running at `http://192.168.5.50:8770/` | `curl -sS -o /dev/null -w '%{http_code}' http://192.168.5.50:8770/` → expect `302` (login redirect) |
| Bugsink project + DSN | Project created in Bugsink, DSN in hand | See §1 |
| Production host → Bugsink network | The container can reach `192.168.5.50:8770` directly (same LAN; the `192.168.5.101:7890` proxy is not involved) | Run the curl above **on the production host** |
| Image dependencies | The new image ships the OTel/sentry-sdk dependencies | See the build steps in §3 (the Dockerfile regenerates requirements from `uv.lock` at build time) |
| Ansible Vault | Holds `~/.ansible-vault/progress.pwd` | See §2 |

> Tip: acceptance already verified end-to-end delivery (HTTP 200) with the DSN `http://98f360b91ad9474d9144c44327913cf0@192.168.5.50:8770/2` (project_id=2). Production can reuse that project as-is or create a dedicated one.

---

## 1. Prepare the Bugsink project and DSN

1. Open `http://192.168.5.50:8770/` in a browser and log in.
2. Open (or create) the target project → Project Settings, copy the **DSN**, which looks like:
   ```
   http://<public-key>@192.168.5.50:8770/<project-id>
   ```
   Note down the full DSN (public key and project-id included); it is injected as a secret later.
3. (Optional) Clean up the test events left over from acceptance: in project 2, resolve/delete the following event_ids: `58210c809fdf426d8b28f5d262e2cb0d`, `98db4309a3b34feab782f3081fe1084b`, `db107e65b17546d9873aa0e825e90e43`, `c9fd1ee92ea3451d948954fd94756ce0`, `e5e9f9ba69a14d8eb9eee53ab729ae22`, `3fd42583bdd242b2a347946ac4b4e03c`.

---

## 2. Inject the configuration (Ansible-managed)

Production configuration is rendered by Ansible. The DSN is a secret; by this project's convention it goes into the vault and is referenced as an environment variable in the compose template.

> Enabling through **environment variables** is recommended (the DSN never lands in a config file, stays vault-managed, and is fully owned by Ansible). `[observability]` is **infrastructure** configuration that is re-read on every start, so the environment variable takes effect on its own — no seed-file edit or service restart needed.

### 2.1 Write the DSN into the vault

Each environment's secrets live in `devops/ansible/group_vars/<env>/vault.yml` as **individually encrypted single variables** (auto-loaded by group). The vault passwords are split per environment into two vault-ids — `progress-prod` for the `prod` group (`fn`), `progress-test` for the `staging` group (`oect`) — provided by the avpm keyring (see `vault_identity_list` in `ansible.cfg`). Add a variable to an environment (alongside the existing `gh_token`, `feishu_webhook_url`, and friends) with `scripts/vault.py` (parse/upsert of single-variable blocks, strict single-identity decryption, self-check before writing to disk):

```bash
# 明文从 stdin 读入（剥掉一个尾部换行；--exact 保留字节原样），加密后 upsert
uv run python scripts/vault.py set staging bugsink_dsn --stdin
uv run python scripts/vault.py list --all                        # 各环境变量名 + 加密标签（不解密）
uv run python scripts/vault.py check                             # 全环境全变量解密验证（不输出明文）
uv run python scripts/vault.py get staging bugsink_dsn --quiet   # 解密到 stdout（唯一的明文输出命令，管道给消费方）
```

The equivalent native command (the tool is built on exactly these two primitives; writing it by hand bypasses the pre-write self-check and the structural validation):

```bash
# 单变量加密追加（解密后的明文从 stdin 输入，不落命令行历史）
ansible-vault encrypt_string --vault-id progress-test@~/.local/bin/avpm-client \
  --stdin-name bugsink_dsn >> devops/ansible/group_vars/staging/vault.yml
```

The value looks like `http://<public-key>@192.168.5.50:8770/<project-id>`.

### 2.2 The compose template

`devops/ansible/templates/docker-compose.yml.j2` already carries the observability block with guards — nothing to hand-edit:

```jinja
{% if progress_otlp_endpoint is defined and progress_otlp_token is defined %}
      - OTEL_EXPORTER_OTLP_ENDPOINT={{ progress_otlp_endpoint }}
      - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20{{ progress_otlp_token }}
      - OTEL_EXPORTER_OTLP_COMPRESSION=gzip
      - OTEL_SERVICE_NAME=progress
      - OTEL_RESOURCE_ATTRIBUTES=deployment.environment.name={{ env }}
{% endif %}
{% if bugsink_dsn is defined %}
      - PROGRESS_OBSERVABILITY__BUGSINK__DSN={{ bugsink_dsn }}
{% endif %}
{% if kuma_push_url is defined %}
      - PROGRESS_KUMA_PUSH_URL={{ kuma_push_url }}
{% endif %}
```

Both `progress_otlp_endpoint` and `progress_otlp_token` defined → OTLP mode (all three signals ship to the collector); either missing → the app falls back to local file exporters, which is the deployment-level degradation path. The endpoint lives in plain `group_vars/<env>/env.yml`; the token and the kuma push URL are vault secrets:

```bash
ssh <nas> 'grep ^PROGRESS_OTLP_TOKEN_STAGING= ~/docker/otelcol/.env | cut -d= -f2-' \
  | uv run python scripts/vault.py set staging progress_otlp_token --stdin
```

The collector side (token admission, Grafana provisioning) is infra work on the observability NAS — see [`monitoring.md`](./monitoring.md) for the layout and the acceptance drills, including the unplug drill that proves the file fallback.

### 2.3 (Optional) Go through the Web UI / DB config instead

You can also set `core.observability.bugsink.dsn` from the Web UI's Settings page or via the API (Web-class config, stored in the DB `config` table):

```toml
[core.observability.bugsink]
dsn = "http://<public-key>@192.168.5.50:8770/<project-id>"
environment = "production"
```

> Prefer the env+vault route of §2.1/2.2 (the DSN stays out of files). This section is only the fallback.

Commit the code and template changes, then move on to the build.

---

## 3. Build and push the image

```bash
# 多架构构建并推送到 192.168.5.50:5000（生产 tag 为 :main）
uv run python docker/build.py --push --tags main
```

Confirm the push succeeded (the `192.168.5.50:5000/progress:main` image is updated). The Dockerfile runs `uv export …` during the build stage, so the new dependencies (opentelemetry-*, sentry-sdk) are baked into the image.

---

## 4. Deploy to production

```bash
ansible-playbook -i devops/ansible/hosts.yml devops/ansible/main.yml \
  --vault-password-file ~/.ansible-vault/progress.pwd
```

The playbook renders the compose file → pulls the new image with `pull: always` → recreates the container. Inside the container, s6-overlay brings up Caddy and the FastAPI service; the schedule runs in-process on the scheduler (`schedule.cron` / `PROGRESS_SCHEDULE_CRON`, currently `30 8,22 * * *`).

---

## 5. Post-deploy verification

> The container is named `progress`; the `docker compose` commands below run on the production host under `~/docker/progress/` (that is, `app_path`).

### 5.1 Startup logs confirm initialization
```bash
docker compose logs app 2>&1 | grep -iE "Bugsink error reporting enabled|telemetry"
```
Expect to see `Bugsink error reporting enabled (environment=prod)`. No errors means `sentry-sdk` initialized successfully.

### 5.2 Telemetry files exist (file mode)
```bash
docker exec progress ls -la /app/data/observability/
```
In file mode expect `traces.jsonl` and `metrics.jsonl` to appear (inspect `./data/observability/` on the host). In OTLP mode these stay absent by design — verify remotely instead:

```bash
# On the observability NAS: progress series present and fresh, environment label correct
curl -s http://127.0.0.1:8428/api/v1/query \
  --data-urlencode 'query=count({__name__="process.memory.usage","service.name"="progress"})'
curl -s http://127.0.0.1:8428/api/v1/query \
  --data-urlencode 'query=max(timestamp({__name__="process.memory.usage","service.name"="progress"}))'
```
Then open the progress dashboards in Grafana and confirm the `env` variable lists the deployed environments. The full acceptance checklist (including the unplug drill) lives in [`monitoring.md`](./monitoring.md).

### 5.3 Trigger one run and verify the business-pipeline spans
```bash
# 手动跑一次 run（与 cron 同路径），随后检查 traces
docker exec progress progress run -c /app/config.toml
docker exec progress sh -c "tail -n 3 /app/data/observability/traces.jsonl"
```
Expect spans such as `progress.run`, `progress.integration.repo`, `progress.git.op`, and `progress.ai.call`, with child spans' `parentSpanId` pointing at `progress.run`.

### 5.4 The metrics file
```bash
docker exec progress tail -n 1 /app/data/observability/metrics.jsonl | python3 -m json.tool
```
Expect metrics such as `progress.repos.checked` and `progress.git.op.duration`.

### 5.5 Log-trace correlation
```bash
docker exec progress tail -n 20 /app/data/logs/progress.log
```
Expect JSON log lines carrying `"trace_id": "…", "span_id": "…"` fields.

### 5.6 Bugsink receives events
- Wait for a real check error (if any), or fabricate one temporarily: `python -c "import sentry_sdk; ..."` inside the container is for troubleshooting only;
- Safer: check the Bugsink project page for a new issue; this acceptance pass already confirmed HTTP 200 through both an independent envelope and the sentry-sdk path.

---

## 6. Operations notes

### 6.1 ⚠️ File retention (read before production)
The telemetry files are **append-only with no built-in rotation** and grow **without bound** at 100% sampling. A production rollout **must** configure rotation, or the disk fills up.

On the production host, prefer `logrotate` with `copytruncate` (the exporters hold the file handles and append; `copytruncate` rotates without restarting the process):

Create `/etc/logrotate.d/progress-observability`:
```
/path/to/data/observability/*.jsonl {
    daily
    rotate 14
    compress
    missingok
    notifempty
    copytruncate
    size 100M
}
```
(Replace the path with the actual absolute `data/observability` path on the production host.) Rotate at 100M or daily, keeping 14 compressed archives.

### 6.2 File locations
- Inside the container: `/app/data/observability/{traces,metrics}.jsonl`
- On the host: `<app_path>/data/observability/` (that is, `./data/observability/`)
- Human/AI inspection: see the jq examples in [`observability.md`](./observability.md).

### 6.3 Performance and quotas
- 100% sampling on an internal low-traffic tool: negligible overhead; the CLI (short-lived) uses a synchronous processor, the API (long-running) exports in batches.
- Bugsink quotas: each project keeps 10000 events by default with per-5-minute/hour/month caps; exceeding them returns HTTP 429 (the client backs off automatically). This project's error volume is low and rarely reaches them.

---

## 7. Rollback / turning it off

Clearing the DSN turns Bugsink reporting off — **no image rollback needed**:

- **A. Turn off Bugsink only (keep the image)**: edit `docker-compose.yml.j2`, remove (or empty) `PROGRESS_OBSERVABILITY__BUGSINK__DSN`, and re-run the §4 deploy. After the restart, outbound reporting stops (OTel files still write locally).
- **B. Full rollback**: deploy the previous image and drop the env above.

After a rollback, the already-written `*.jsonl` files and the events already stored in Bugsink stay put; business is unaffected.

---

## 8. Troubleshooting

| Symptom | Investigation |
|---|---|
| No files under `data/observability/` | OTel is always on; the files should appear on their own. Check `docker compose logs app` for instrumentation warnings and confirm the `/app/data/` volume is mounted |
| traces.jsonl empty / spans missing | API path: a single HTTP request generates them; CLI path: wait for cron or run `progress run` manually (the short-lived process force-flushes on exit) |
| Bugsink receives no events | Confirm the DSN is non-empty (`docker exec progress python3 -c "..."` to read the DB config); `curl` connectivity from the production host; confirm the DSN public key and project-id are correct; check whether Bugsink returns 429 (quota); check `progress.log` for a `bugsink dsn empty` warning |
| `trace_id` empty in the logs | Normal: it means the code is not inside a span context; business logs during a `progress run` should carry a value |
| Disk usage grows fast | See §6.1: configure logrotate |

---

## 9. Launch sign-off checklist

- [ ] §0 pre-flight fully satisfied (Bugsink reachable, vault ready)
- [ ] §1 DSN obtained and written into the vault (`bugsink_dsn`)
- [ ] §2 compose template carries the env; code/template changes committed
- [ ] §3 image pushed successfully via `--push`
- [ ] §4 Ansible deploy finished, container recreated
- [ ] §5.1 startup logs show `Bugsink error reporting enabled`
- [ ] §5.2 telemetry files exist
- [ ] §5.3 after one check, traces carry the full span tree
- [ ] §5.6 Bugsink receives events
- [ ] §6.1 logrotate (or equivalent rotation) configured
- [ ] §7 rollback steps reviewed
