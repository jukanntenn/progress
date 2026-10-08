# RFC: Per-tracker proxy routing for changelog fetches

Status: proposed

English | [中文](2026-10-08-changelog-proxy-fetch.zh.md)

## Problem

Changelog trackers fetch arbitrary URLs through the shared aiohttp session. Since the [spec 07 HTTP client rework](../../../../specs/redesign/07-git-http-clients.md), that session is created with `trust_env=False` and never proxies on its own: the configured proxy (`core.github.proxy`) is threaded per request only into the GitHub clients, git subprocesses, and — following that precedent — the v2ex client. Changelog's `_fetch_text` passes no `proxy=`, so every tracker whose URL is unreachable without a proxy fails on every check, and one failing tracker degrades the integration to `partial`/`failed`. The [changelog spec](../../../../specs/integrations/changelog.md) still documented the pre-rework assumption ("proxy via the shared ClientSession's environment variables"), so the severed path was never noticed. The deployed tracker set mixes directly reachable URLs (u-tools.cn, zcode.z.ai) with proxy-only ones (raw.githubusercontent.com), so neither "always proxy" nor "never proxy" is correct.

## Proposal

### Per-tracker opt-in, single proxy source

`ChangelogItemConfig` — and the `ChangelogTracker` row `sync` mirrors it onto — gains `use_proxy: bool = false`. A tracker with `use_proxy = true` has its fetch sent with the per-request `proxy=` argument set to `core.github.proxy`, the same single knob the GitHub clients and v2ex already consume; no new proxy URL field exists to drift out of sync. Default `false` keeps every existing tracker's behavior identical on upgrade: the proxy applies only where the user asked for it.

### Fail loud on half configuration

`use_proxy = true` with an empty `core.github.proxy` returns `failed` for that tracker with an error naming the missing setting, before any request is made. Silently attempting direct would reproduce today's opaque timeout failure — the exact confusion this change removes.

### Everything else rides existing machinery

The settings editor renders the field from the section schema; `sync` mirrors it onto the row like `enabled`/`parser_type`; one migration adds a boolean column; per-request proxying is the established aiohttp 3.10 pattern (`ProxiedGitHubAPI`, `V2exClient`), so the shared session stays `trust_env=False` and Feishu/MarkPost/AI/Miniflux traffic stays direct.

## Alternatives considered

**Route all changelog fetches through `core.github.proxy` (v2ex-style blanket).** v2ex's traffic is one uniformly blocked site; a changelog tracker list is heterogeneous by design, and the deployed set mixes directly reachable URLs with proxy-only ones. Blanket proxying would newly depend on the proxy reaching every tracker's host, regressing currently working trackers with no per-tracker escape hatch.

**A per-tracker proxy URL field.** Duplicates the one proxy URL a deployment has into N tracker entries — a second source of truth for the same fact; v2ex already established `core.github.proxy` as the project's single proxy knob.

**Honor `HTTP_PROXY`/`HTTPS_PROXY` (`trust_env=True`).** Rejected by spec 07: it drags every HTTP client in the process — Feishu, MarkPost, AI, Miniflux — through the proxy meant for blocked-external traffic; per-request threading is the supported way to scope a proxy to the requests that need it.

**Auto-proxy well-known blocked domains.** Reachability is a deployment fact the user knows and the process cannot verify; a hardcoded domain list is a magic heuristic the config cannot override.

## Acceptance criteria

- A tracker with `use_proxy = true` and a non-empty `core.github.proxy`: its fetch request carries `proxy=<configured url>`; check behavior is otherwise unchanged.
- A tracker with default `use_proxy = false`: fetched directly even when a proxy is configured.
- `use_proxy = true` with empty `core.github.proxy`: the tracker's check returns `failed` with an error naming `core.github.proxy`; no request is sent; other trackers are unaffected.
- Existing DB config rows without the key load unchanged (`false`); `sync` mirrors `use_proxy` changes onto rows without touching the watermark.
- The settings UI renders the toggle in the changelog section from the section schema alone.

## Risks

- The opted-in tracker's host must be reachable *through* the proxy; a proxy that blocks it turns a direct timeout into a proxied error. The existing fetch error paths still name the tracker and URL either way.
- The proxy URL is resolved from the integration's held `CoreConfig` at check time — the same freshness semantics as the repo/proposal/v2ex clients, not a new cache.
- One more mirrored boolean on the row: divergence between config and row is bounded by the sync comparison and the CI migration drift gate.
