# Configuration

Progress uses a **two-file configuration model** (spec 02) that physically
separates infrastructure settings (owned by Ansible/deployer) from
user-facing settings (owned by the Web UI / DB). The two classes never
overlap, so a deploy cannot clobber a user edit and vice versa.

## How configuration is split

| Class | Owner | Storage | Mount | Contents |
|---|---|---|---|---|
| **Ansible** | Deployer | `config.toml` | read-only file | `state_home` only |
| **Core Web** | Web UI / user | DB `config` table (`section="core"`) | DB (writable) | language, timezone, github, analysis, markpost, notification, observability, web |
| **Plugin** | Web UI / user | DB `config` table (`section=<plugin>`) | DB (writable) | per-integration config (`repo`, `changelog`, `proposal`) |

`state_home` is the single infrastructure key — the root directory for all
runtime data (DB, logs, cloned repos, observability exports). Every other
path is derived from it.

## The two files

### `config.toml` (Ansible class)

Carries **only** `state_home`. Mounted read-only in Docker.

```toml
state_home = "data"
```

Environment variable override: `PROGRESS_STATE_HOME`.

### `config.db.toml` (DB seed, Web class)

A **seed file** that mirrors the `config` table layout: every top-level table
is one `section` row. Place it next to `config.toml`. On startup it is imported
into the DB (see [Seed import](#seed-import)).

```toml
[core]
language = "en"
timezone = "UTC"

[core.github]
gh_token = ""                       # SecretStr; empty → GitHub tracking disabled + warning
proxy = ""                          # HTTP proxy for aiohttp + git (e.g. "http://127.0.0.1:7890")

[core.analysis]
provider = ""                       # e.g. "anthropic"; empty → AI disabled (truncation fallback)
model = ""                          # e.g. "claude-sonnet-4"
api_key = ""                        # SecretStr
base_url = ""                       # custom endpoint for OpenAI-compatible services; empty → provider default
language = "en"

[core.markpost]
enabled = false
url = ""                            # SecretStr; format: https://host/post_key (e.g. https://markpost.cc/mpk-abc123)
max_batch_size = 1048576

[[core.notification.channels]]
type = "console"
enabled = true

[[core.notification.channels]]
type = "email"
enabled = false
host = "smtp.example.com"
port = 465
user = "sender@example.com"
password = ""                       # SecretStr
from_addr = "progress@example.com"
recipient = ["alice@example.com"]
starttls = false
ssl = true

[[core.notification.channels]]
type = "feishu"
enabled = false
webhook_url = ""                    # SecretStr

[core.observability.bugsink]
dsn = ""                            # SecretStr; empty → error capture disabled
environment = "production"

[core.web]
base_url = ""                       # public base URL for report back-links
```

Copy `config.example.db.toml` as a starting point.

## Seed import

When `config.db.toml` exists next to `config.toml`, every startup re-imports it
into the DB `config` table:

- **Priority**: `DB > seed > code defaults`. The seed only fills keys the DB
  doesn't already have — Web UI edits survive a restart.
- **All sections** are imported: `[core]` plus plugin sections (`[repo]`,
  `[changelog]`, `[proposal]`), so each integration reads its config from the DB.
- **Validation**: `[core]` passes through; plugin sections are validated against
  their registered Pydantic schema. A failing section is logged and skipped.
- **Production**: operators must ensure `config.db.toml` does **not** exist
  (the DB is the single source of truth; `.gitignore` excludes it). Edit via the
  Web UI or `PUT /api/v1/config/{section}`.
- **Testing / first deploy**: place `config.db.toml` to seed initial config
  without touching the Web UI.

## Editing configuration

- **Web UI** — the *Configuration* page renders a form from the JSON Schema
  (`GET /api/v1/config/schema`) and writes via `PUT /api/v1/config/{section}`.
- **API** — `GET /api/v1/config` returns all sections (SecretStr fields masked
  as `**********`); `PUT /api/v1/config/{section}` validates and writes one.
- **Seed file** — edit `config.db.toml` and restart (re-imports into the DB).

Secrets (`gh_token`, `api_key`, `password`, `webhook_url`, `dsn`, markpost
`url`) are `pydantic.SecretStr`: they are stored as real values in the DB
(trusted internal store) but serialized to `**********` in every API response.
Submitting the mask value unchanged preserves the stored value.

## Zero configuration

Every optional feature degrades gracefully when its prerequisite is missing —
the system never fails to start:

- No `github.gh_token` → GitHub tracking (release/owner discovery) disabled + warning.
- No `analysis.provider`/`api_key` → AI analysis disabled; reports use the default title.
- `markpost.enabled=true` but empty `url` → MarkPost publishing disabled + warning.
- No notification channels enabled → dispatch skipped.

## Precedence

- **Ansible** (`state_home`): `PROGRESS_STATE_HOME` env > `config.toml` > default `"data"`.
- **Web class**: `PROGRESS_*` env vars (prefix `PROGRESS_`, separator `__`) override
  on top of DB + seed at startup.

## Plugin configuration

Each integration owns a `config` table section (keyed by `Integration.name`).

### `repo` (section `"repo"`)

```toml
[repo]
first_run_lookback_commits = 3      # commits analyzed on a repo's first run
max_reenabled_lookback_commits = 50 # commits analyzed when a repo is stale-reenabled
max_reenabled_lookback_releases = 20 # releases analyzed when a repo is stale-reenabled
reenabled_stale_days = 7            # days without a check before stale reenabled

[[repo.repos]]
url = "vitejs/vite"
branch = "main"
enabled = true
track_commits = true                # enable commit diff tracking
track_releases = true               # enable release tracking

[[repo.owners]]
type = "organization"               # "organization" | "user"
name = "bytedance"
enabled = true
```

When a repo's `last_check_time` exceeds `reenabled_stale_days`, the next run uses
`max_reenabled_lookback_commits` / `max_reenabled_lookback_releases` as the
backfill window instead of the normal incremental diff. Setting `track_commits`
or `track_releases` to `false` advances the respective checkpoint without
analysis, eliminating the gap on re-enable.

### `changelog` (section `"changelog"`)

```toml
[[changelog.trackers]]
name = "Vite"
url = "https://raw.githubusercontent.com/vitejs/vite/main/packages/vite/CHANGELOG.md"
parser_type = "markdown_heading"    # "markdown_heading" | "html_chinese_version"
enabled = true
```

- `markdown_heading`: Markdown with `## 1.2.3` headings.
- `html_chinese_version`: HTML with patterns like `uTools v7.5.1`.

### `proposal` (section `"proposal"`)

```toml
[proposal]
trackers = ["eip", "erc", "pep", "rfc", "dep"]
```

| Kind | Repository | Description |
|---|---|---|
| `eip` | ethereum/EIPs | Ethereum Improvement Proposals |
| `erc` | ethereum/ercs | Ethereum Request for Comments |
| `pep` | python/peps | Python Enhancement Proposals |
| `rfc` | rust-lang/rfcs | Rust Request for Comments |
| `dep` | django/deps | Django Enhancement Proposals |

### `feed` (section `"feed"`)

Miniflux RSS reader connection. Empty `base_url` → feed integration disabled
+ warning (zero config). See `specs/integrations/feed.md`.

```toml
[feed]
base_url = "https://miniflux.example.org"   # empty → disabled
api_key = "MF-api-key-xxxx"                  # SecretStr; base_url set but empty → disabled
```

Which feeds to track is **data-source driven** (decided entirely by what
Miniflux is subscribed to), so this section carries only the Miniflux
credentials — no feed list. Per-feed dedup water marks live in the
`feed_trackers` state table, advanced inside `run`.
