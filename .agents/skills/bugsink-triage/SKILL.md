---
name: bugsink-triage
description: End-to-end workflow for triaging production errors from the deployed Bugsink instance and driving each one to a verified, committed code fix in the progress project. Covers fetching issues and events through the Bugsink REST API, root-causing against local source, fixing with regression tests, re-verifying against the real production payload, and resolving the issue after deploy. Use this whenever the user mentions Bugsink, production errors / crashes / exceptions, Sentry-style error events, asks to investigate or fix what is failing in prod, review production issues, or triage errors — even when they do not name Bugsink explicitly.
---

# Bugsink production-error triage

Bugsink is a self-hosted, Sentry-compatible error tracker. The `progress` app ships errors to it via `sentry-sdk` (configured in `src/progress/telemetry.py`). This skill is the runbook for going from "something is failing in prod" to a committed, verified fix and a resolved Bugsink issue. It was distilled from a real session that found and fixed five production issues end-to-end.

## Access

- Base URL: `http://192.168.5.50:8770`
- REST API root: `/api/canonical/0/` (DRF router). Schema at `/api/canonical/0/schema/`, Swagger UI at `/api/canonical/0/schema/swagger-ui/`.
- Auth: `Authorization: Bearer <token>`. Token stored at `~/.bugsink_token` (40 lowercase hex chars); created by a Bugsink superuser in the UI at `/bsmain/auth_tokens/`.
- `progress` project id: **2**. Confirm via the projects endpoint on first use — do not hard-code assumptions across deploys.

A helper wraps auth + base URL so each call stays short and the token never appears inline:

```bash
bash .claude/skills/bugsink-triage/scripts/bugsink.sh GET "/projects/"
```

If `~/.bugsink_token` is missing, ask the user to create a token in the Bugsink UI and store it:
`printf '%s' '<token>' > ~/.bugsink_token && chmod 600 ~/.bugsink_token`.

## The workflow

### 1. List issues (triage)

```bash
bash .claude/skills/bugsink-triage/scripts/bugsink.sh GET "/issues/?project=2&sort=last_seen&order=desc"
```

Each issue carries `calculated_type` / `calculated_value` (error type + message), `first_seen` / `last_seen`, `digested_event_count` (occurrences), `is_resolved` / `is_muted`, and a `friendly_id` like `PROGRESS-5`. Prioritise issues that are **recurring** (`digested_event_count` > 1), **recent**, and **real exceptions** (the `calculated_type` is an exception class) over `Log Message` types — those last ones are usually downstream symptoms.

### 2. Get the latest event, then its RAW data

Two calls. The events list is lightweight (no stacktrace); the detail endpoint has everything — exception frames, locals, breadcrumbs, tags, modules.

```bash
# latest event id for an issue (pass the issue UUID — friendlier than friendly_id across endpoints)
EID=$(bash .claude/skills/bugsink-triage/scripts/bugsink.sh GET "/events/?issue=<ISSUE_UUID>&order=desc" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['results'][0]['id'])")

# full payload — this is the source of truth
bash .claude/skills/bugsink-triage/scripts/bugsink.sh GET "/events/$EID/" > /tmp/event.json
```

There is also a rendered `/events/<id>/stacktrace/` endpoint that is convenient for skimming. **Do not trust it for large or truncated local-variable values.** It has been observed disagreeing with the raw payload (e.g. showing a closing `}` that is not actually in the captured value). When a local looks surprising, always fall back to the raw `data` from `/events/<id>/`.

### 3. Root-cause against the local source

Stack frames carry `abs_path` like `/app/src/progress/contrib/repo/analysis.py` (the Docker container path). Map these to the repo by dropping the `/app/` prefix → `src/progress/...`. Read the real, current source before proposing a fix: the deployed build can lag the working tree, and the fix must target the code as it is now.

Pull the decisive evidence with a small Python snippet instead of eyeballing 100 KB+ of JSON:

```python
import json
data = json.load(open("/tmp/event.json"))["data"]
for f in data["exception"]["values"][0]["stacktrace"]["frames"]:
    print(f["filename"], f["lineno"], f.get("function"), "vars:", f.get("vars"))
```

Breadcrumbs (`data.breadcrumbs.values`) show what led up to the failure — git subprocess calls, the `claude -p …` invocation, etc. Tags carry `component` / `repo` / `provider` / `stage`. `release` and `environment` confirm which deployment produced it.

### 4. Fix + test

Apply the fix against the local source. Add a regression test that uses the **actual production payload** from the event as its fixture. This is the strongest evidence the fix addresses the real failure rather than a guess at what might have happened — a truncated or malformed string recovered from a real event becomes the test input that would have reproduced the bug.

```bash
uv run pytest -v   # full suite — the change must not break anything else
uv run ruff check  # lint gate (a hook enforces this on every edit)
```

Watch the lint/format hook: it runs `ruff --fix` after edits and will delete an import that is not yet used. When introducing a new dependency, add the import in the same edit that introduces its first use, or expect to re-add it once the hook has run.

### 5. Re-verify end-to-end against the real event data

Before declaring done, feed the genuine captured payload through the fixed code path and confirm it now succeeds where it previously raised. This closes the loop between "the event said X failed" and "X now works":

```python
from progress.contrib.repo.analysis import AnalysisResultParser
real_output = ...  # extract from /tmp/event.json as in step 3
summary, detail = AnalysisResultParser().parse(real_output)   # previously raised
```

### 6. Resolve the Bugsink issue (after deploy)

The fix only takes effect once deployed. After the deploy lands, mark the issue resolved so the dashboard reflects reality:

```bash
bash .claude/skills/bugsink-triage/scripts/bugsink.sh POST "/issues/<ISSUE_UUID>/resolve/"
```

For `Log Message` issues that may or may not recur, resolve only after confirming they stop appearing post-deploy.

## Gotchas worth remembering

- **`id` vs `event_id`.** The detail and stacktrace routes take the internal `id` (Bugsink's own UUID), not the sentry client's `event_id`. The events list returns both — use `id`.
- **`_meta` records truncation.** `sentry-sdk` truncates large values at capture time and notes what it cut in the top-level `_meta` field. If a local variable looks incomplete, check `_meta` to tell capture-time truncation apart from a value that was genuinely that way at runtime.
- **Rendered vs raw payload.** See step 2 — prefer `/events/<id>/` raw `data` over `/events/<id>/stacktrace/` whenever locals are large or look truncated.
- **`digested` vs `stored` counts.** A project's `digested_event_count` can exceed `stored_event_count`: high-frequency duplicate events are deduped or rate-limited before storage. Triage should key off the issue list, not these totals.
- **AI-tool env can differ per host.** The `claude` CLI can route to different backends per environment (e.g. an Anthropic-compatible proxy). When diagnosing AI-output issues (truncation, malformed JSON), the production container's `ANTHROPIC_BASE_URL` / `CLAUDE_CODE_MAX_OUTPUT_TOKENS` / model may explain the behaviour — ask the user to check the prod container env, since it is not visible from a dev host.
