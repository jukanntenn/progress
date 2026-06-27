# Manual Verification Checklist

Human-executable verification of Progress, covering both the **configuration
refactor** and the **core business logic** (repo tracking, analysis, reporting,
notifications, proposal/changelog tracking, owner monitoring).

Each step lists **Action**, **Expected**, and **Verify**. Steps that need
network / AI / an external service are marked. Run them in order the first
time; later sections depend on the config seeded in Section A.

## 0. Prerequisites

- `uv` (Python) and `pnpm` (frontend) installed; `uv sync` and
  `cd web && pnpm install` run.
- For **repo tracking with AI analysis**: the `claude` or `codex` CLI installed
  and authenticated, **or** set `analysis.provider = "truncate"` for a no-AI
  smoke test (report content is a truncated diff — still exercises the whole
  pipeline except the AI call).
- For **owner/proposal/changelog tracking**: outbound network to GitHub.
- Optional external services: Feishu webhook / SMTP server (only for the
  corresponding notification steps; the `console` channel needs nothing).

## 1. Environment setup (isolated)

Use a throwaway database so your real `data/progress.db` is never touched.

```bash
# 1.1 copy the seed file
cp config.example.toml config.toml
#     -> set data_dir to an absolute scratch dir, e.g. /tmp/progress-verify
#     -> set [github] gh_token (any non-empty value works for cloning public repos;
#        a real PAT is needed for private repos / higher rate limits)
#     -> set [analysis] provider = "truncate" for the no-AI smoke path
#     -> keep 1 small public repo under [[repos]] (e.g. "octocat/Hello-World")

# 1.2 start backend (port 5000 = the frontend's default proxy target)
PYTHONPATH=src CONFIG_FILE=config.toml uv run fastapi dev --port 5000

# 1.3 in another shell, start frontend
cd web && pnpm dev          # http://localhost:3000
```

**Verify:** backend log says `Application startup complete`; opening
`http://localhost:3000/` loads the reports page without errors.

> Tip: to fully reset mid-test, delete the scratch `data_dir` and restart the
> backend — the first run re-seeds from `config.toml`.

---

## Section A — Configuration

These mirror the automated report
([`verification-config-refactor.md`](./verification-config-refactor.md)) as
hands-on steps, and add the **owner-edit fix**.

### A1. File seeds the DB on first run
- **Action:** with a fresh scratch DB, start the backend (1.2).
- **Expected:** the DB blob + `repositories`/`github_owners` tables are
  populated from `config.toml`.
- **Verify (DB):**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT version, json_extract(data,'$.analysis.provider') FROM app_config;"
  sqlite3 <data_dir>/progress.db "SELECT name, branch, enabled FROM repositories;"
  sqlite3 <data_dir>/progress.db "SELECT owner_type, name, enabled FROM github_owners;"
  ```
  Values match `config.toml`; `app_config.version = 1`.
- **Verify (UI):** `http://localhost:3000/config` shows the values and
  "Stored in the database (version 1)".

### A2. Web edit persists and does not touch the file
- **Action:** on the Configuration page, change a scalar (e.g.
  `Analysis → timeout`), click **Save**.
- **Expected:** toast "Configuration saved"; page shows `version 2`; the value
  in the DB changed; `config.toml` is unchanged.
- **Verify:**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT version, json_extract(data,'$.analysis.timeout') FROM app_config;"
  grep "timeout" config.toml        # still the original value
  ```

### A3. Owner add/edit/remove via the web UI *(the recent fix)*
- **Action:** on the Configuration page → Owners section: click **Add Owner**,
  set type + name, click the Owners **Save**.
- **Expected:** toast "Owners saved" (NOT "Save failed"); `version` is unchanged
  (owners are a separate table); the new owner appears in the DB.
- **Verify:**
  ```bash
  sqlite3 <data_dir>/progress.db "SELECT owner_type, name, enabled FROM github_owners;"
  curl -s http://127.0.0.1:5000/api/v1/config/owners | python3 -m json.tool
  ```
- **Also try:** toggle `enabled` off and Save → row kept, `enabled=0` (replace
  preserves disabled owners rather than deleting them). Remove a row and Save →
  row pruned.
- **Fail signal:** a `422` / "Save failed" toast means the `type`/`owner_type`
  regression returned.

### A4. Repos add/edit/remove via the web UI
- **Action:** Repositories section → **Add Repository** → enter URL → Save.
- **Expected:** "Repositories saved"; new repo in `repositories` table; existing
  rows keep their `id` and runtime state.
- **Verify:** `sqlite3 <data_dir>/progress.db "SELECT id,name,url,enabled FROM repositories;"`

### A5. Secret masking & round-trip
- **Action:** set `GitHub → gh token` to a new value, Save; then change another
  field and Save *without re-entering the token*.
- **Expected:** GET always shows `********`; the DB stores the real value; the
  second save preserves it.
- **Verify:** `GET /api/v1/config` shows `"gh_token": "********"`, while
  `sqlite3 ... "SELECT json_extract(data,'$.github.gh_token') FROM app_config;"`
  holds the real token both times.

### A6. File is ignored after seeding (the core guarantee)
- **Action:** edit an app-config value directly in `config.toml` (e.g.
  `analysis.timeout = 999`), then restart the backend (1.2).
- **Expected:** `GET /api/v1/config` still returns the **DB** value, not 999.
- **Verify:**
  ```bash
  curl -s http://127.0.0.1:5000/api/v1/config | python3 -m json.tool
  ```
- **Restore path:** `uv run progress -c config.toml config import --force`
  is the only way the file reaches the DB; afterward the DB reflects the file
  and `version` bumps. `config export` dumps DB → TOML.

---

## Section B — Core business logic

### B1. Repository tracking — first run `*(network; AI optional)*`
- **Action:** `uv run progress -c config.toml check`
- **Expected:** each enabled repo is cloned into `workspace_dir`; the first
  `analysis.first_run_lookback_commits` commits are analyzed; a report is
  generated per repo; the repo's `last_commit_hash` is recorded.
- **Verify (DB):**
  ```bash
  sqlite3 <data_dir>/progress.db \
    "SELECT name, last_commit_hash IS NOT NULL AS has_checkpoint, last_check_time FROM repositories;"
  sqlite3 <data_dir>/progress.db \
    "SELECT id, repo_id, title, commit_count, created_at FROM reports ORDER BY id DESC LIMIT 5;"
  ```
- **Verify (filesystem):** `ls <workspace_dir>` shows the cloned repo.
- **Verify (UI):** `http://localhost:3000/` lists the **aggregated** report
  (the list shows reports with no single repo owner); click it →
  `/report/<id>` renders the analysis (AI summary if a real provider was used;
  truncated diff if `truncate`). Per-repo reports have a `repo_id` and are
  viewable by id but are not in the list.

### B2. Idempotent re-run (no new commits)
- **Action:** run `check` again immediately.
- **Expected:** no new report (nothing past `last_commit_hash`); no duplicate
  reports. `reports` row count unchanged.
- **Verify:** compare the `reports` count / max `id` before and after.

### B3. New-commit detection `*(network; AI optional)*`
- **Action:** force re-analysis of a known commit without waiting for upstream:
  ```bash
  sqlite3 <data_dir>/progress.db \
    "UPDATE repositories SET last_commit_hash = '<older-or-null-sha>' WHERE name='<the repo>';"
  uv run progress -c config.toml check
  ```
  (Or wait for real upstream commits and re-run.)
- **Expected:** a new report covering the commits since the recorded checkpoint;
  `last_commit_hash` advances.
- **Verify:** a new row in `reports` for that repo; UI shows it.

### B4. Owner monitoring `*(network)*`
- **Prereq:** add an active owner via the UI (Section A3) whose account has
  recent public repos; ensure a notification channel exists (B7 console).
- **Action:** `uv run progress -c config.toml check`
- **Expected:** newly created repos of that owner are discovered and surfaced
  (report + notification). Per the design, discovered repos are **ephemeral**
  — they are reported/notified but **not** added to the `repositories` table.
- **Verify:** console output / log contains a discovered-repo entry for the
  owner; `repositories` table is unchanged (no auto-promotion).

### B5. Proposal tracking `*(network)*`
- **Prereq:** in the config blob (UI → Proposal Trackers), enable one or more
  kinds, e.g. `proposal_trackers = ["pep"]`. Run:
  `uv run progress -c config.toml track-proposals` (or `check`).
- **Expected:** the tracker repo is cloned; proposals are parsed; new / status-
  changed (accepted/rejected/withdrawn) proposals trigger a notification.
- **Verify:** tracker tables populated; on a second run with no changes, no new
  proposal events. `--trackers-only` skips repo tracking:
  `uv run progress -c config.toml check --trackers-only`.

### B6. Changelog tracking `*(network)*`
- **Prereq:** add a `[[changelog_trackers]]` entry (e.g. a CHANGELOG.md raw URL,
  parser `markdown_heading`) via the UI.
- **Action:** `uv run progress -c config.toml check`
- **Expected:** current version parsed from the changelog; on a later run with a
  newer version, a merged release report + notification is produced.
- **Verify:** `changelog_tracker`-related rows/notifications reflect the parsed
  version; re-run with no version change produces nothing new.

### B7. Notifications
- **Console (no external deps):** set a `console` notification channel (UI →
  Notification), run `check` with a triggering event (new commit / proposal /
  release). **Expected:** the notification message prints to stdout / the log.
- **Feishu `*(external)*`:** add a Feishu channel with a real webhook URL;
  trigger an event. **Expected:** a message lands in the Feishu group.
- **Email `*(external)*`:** add an email channel with valid SMTP creds;
  trigger an event. **Expected:** an email arrives at the recipient.
- **Verify secret masking:** the Feishu `webhook_url` and email `password` show
  as `********` in `GET /api/v1/config` but work when sending.

### B8. Reports & RSS
- **UI:** `http://localhost:3000/` paginated report list; open a report → full
  content at `/report/<id>`.
- **API:**
  ```bash
  curl -s "http://127.0.0.1:5000/api/v1/reports?page=1" | python3 -m json.tool
  curl -s http://127.0.0.1:5000/api/v1/reports/<id> | python3 -m json.tool
  ```
  The list returns aggregated/global reports (`repo_id` null — repo-update
  rollup, proposal, changelog, owner-discovered); page size is server-fixed
  (10). Any report, including per-repo ones, is fetchable by id via the
  detail endpoint.
- **RSS:** `curl -s http://127.0.0.1:5000/api/v1/rss | head` → valid RSS XML
  listing recent reports. Subscribe in a feed reader to confirm.

---

## Section C — Edge cases & robustness

- **C1. Invalid repo URL:** add a repo with `url = "not-a-url"` via the API →
  `PUT /api/v1/config/repos` returns **422**; UI shows a validation error.
- **C2. Nonexistent repo:** seed a repo that doesn't exist on GitHub, run
  `check`. **Expected:** tracked gracefully (skipped/logged), no crash, no
  report.
- **C3. Empty config (no repos/owners):** run `check` on a freshly seeded DB
  with no repos. **Expected:** completes cleanly, no reports.
- **C4. Optimistic-lock conflict:** open the config page in two tabs, edit+save
  in tab 1, then save in tab 2. **Expected:** tab 2 gets a 409 / "modified
  elsewhere" toast and refreshes. (Reproducible via API:
  `POST /api/v1/config` with a stale `version`.)
- **C5. Validation rejection:** `POST /api/v1/config` with invalid data (e.g.
  missing `[github]`) → **400** with a readable error.
- **C6. Restart preserves everything:** restart the backend after several edits
  — all DB config and reports are intact; nothing is re-seeded/overwritten.

---

## Section D — Cleanup

```bash
# stop servers (Ctrl+C in each shell), then:
rm -rf <data_dir>          # scratch DB, cloned repos, logs
rm -f config.toml          # throwaway seed (config.example.toml is untouched)
```

Your real `data/progress.db` and any production config are never affected as
long as `data_dir` pointed at the scratch directory.

---

## Pass / fail summary

| Area | Steps | Key pass signal |
|---|---|---|
| Config: seed | A1 | DB matches file, `version=1` |
| Config: web edit | A2, A4, A5 | DB changes, file unchanged, secrets masked |
| Config: owner fix | A3 | owner save succeeds (no 422) |
| Config: file ignored | A6 | DB value survives file edit + restart |
| Repo tracking | B1–B3 | report generated; re-run idle; new commit → new report |
| Owner monitoring | B4 | discovered repos surfaced, not auto-added |
| Proposal tracking | B5 | proposals parsed; changes notified |
| Changelog tracking | B6 | versions detected; new release reported |
| Notifications | B7 | console always; feishu/email when configured |
| Reports & RSS | B8 | UI + API + RSS all return content |
| Robustness | C1–C6 | errors handled, no crashes, no silent clobbering |

A step **fails** if the observed result diverges from **Expected**; record the
command output / screenshot and the DB state for triage.
