# RFC: Per-tracker proxy routing for changelog fetches

Status: proposed

English | [中文](2026-10-08-changelog-proxy-fetch.zh.md)

## Problem

Changelog trackers fetch arbitrary URLs through the shared aiohttp session. Since the [spec 07 HTTP client rework](../../../../specs/redesign/07-git-http-clients.md), that session is created with `trust_env=False` and never proxies on its own: the configured proxy (`core.github.proxy`) is threaded per request only into the GitHub clients, git subprocesses, and — following that precedent — the v2ex client. Changelog's `_fetch_text` passes no `proxy=`, so every tracker whose URL is unreachable without a proxy fails on every check, and one failing tracker degrades the integration to `partial`/`failed`. The [changelog spec](../../../../specs/integrations/changelog.md) still documented the pre-rework assumption ("proxy via the shared ClientSession's environment variables"), so the severed path was never noticed. The deployed tracker set mixes directly reachable URLs (u-tools.cn, zcode.z.ai) with proxy-only ones (raw.githubusercontent.com), so neither "always proxy" nor "never proxy" is correct.

## Proposal

### A proxy URL per tracker, decoupled from the GitHub proxy

`ChangelogItemConfig` — and the `ChangelogTracker` row `sync` mirrors it onto — gains `proxy: str = ""`. A non-empty value is the HTTP(S) proxy URL used for that tracker's fetch, threaded as the per-request `proxy=` argument; empty (default) fetches directly. The field is independent of `core.github.proxy`: the GitHub proxy serves GitHub/git/v2ex traffic, and changelog URLs — arbitrary hosts, not GitHub services — carry their own routing. Default empty keeps every existing tracker's behavior identical on upgrade.

### Malformed URLs fail at config time

A non-empty `proxy` must start with `http://` or `https://`; anything else (a bare `host:port`, a `socks5://` URL the HTTP client cannot use) is rejected by config validation — 422 on PUT, load-time degrade-to-defaults with a logged warning for a stored bad value — instead of surfacing as an opaque aiohttp error mid-run.

### Everything else rides existing machinery

The settings editor renders the field from the section schema; `sync` mirrors it onto the row like `enabled`/`parser_type`; one migration adds a varchar column; per-request proxying is the established aiohttp 3.10 pattern (`ProxiedGitHubAPI`, `V2exClient`), so the shared session stays `trust_env=False` and Feishu/MarkPost/AI/Miniflux traffic stays direct.

The migration declares the column with `db_default=""`, not only a python-side `default`: tortoise renders only `db_default` into the DDL, and SQLite rejects `ADD COLUMN ... NOT NULL` without a database-level default — the failure is swallowed by the never-crash migration policy, leaving the new code running against the old schema. Earlier `AddField` migrations with python-only defaults (e.g. `0002`'s `rule_success_count`) only ever took the bootstrap duplicate-column fake-apply path on deployed databases, so the invalid DDL shape went unnoticed until this migration had to run for real.

## Alternatives considered

**Reuse `core.github.proxy` via a per-tracker `use_proxy` boolean.** The v2ex precedent makes one shared knob look sufficient, but v2ex's traffic is a single uniformly blocked site while a changelog list is arbitrary hosts: coupling changelog fetches to the GitHub proxy makes the GitHub setting load-bearing for unrelated URLs and makes GitHub-proxy edits risk changelog behavior. Rejected in review for this coupling.

**Route all changelog fetches through `core.github.proxy` (blanket).** The deployed tracker set mixes directly reachable URLs with proxy-only ones; blanket proxying would newly depend on the proxy reaching every tracker's host, regressing currently working trackers with no per-tracker escape hatch.

**Honor `HTTP_PROXY`/`HTTPS_PROXY` (`trust_env=True`).** Rejected by spec 07: it drags every HTTP client in the process — Feishu, MarkPost, AI, Miniflux — through the proxy meant for blocked-external traffic; per-request threading is the supported way to scope a proxy to the requests that need it.

**Auto-proxy well-known blocked domains.** Reachability is a deployment fact the user knows and the process cannot verify; a hardcoded domain list is a magic heuristic the config cannot override.

## Acceptance criteria

- A tracker with a non-empty `proxy`: its fetch request carries `proxy=<that url>`; check behavior is otherwise unchanged.
- A tracker with empty `proxy`: fetched directly even when `core.github.proxy` is configured.
- A `proxy` value not starting with `http://`/`https://`: rejected by config validation (422 on PUT); a stored bad value degrades to defaults with a logged warning.
- Existing DB config rows without the key load unchanged (`""`); `sync` mirrors `proxy` changes onto rows without touching the watermark.
- The settings UI renders the field in the changelog section from the section schema alone.

## Risks

- The tracker's host must be reachable *through* its configured proxy; a proxy that blocks it surfaces through the normal fetch error paths, which still name the tracker and URL.
- One more mirrored varchar on the row: divergence between config and row is bounded by the sync comparison and the CI migration drift gate.
- Scheme validation is the only static check; a well-formed but wrong URL (right scheme, wrong host) fails only at fetch time — same visibility as any other network misconfiguration.
