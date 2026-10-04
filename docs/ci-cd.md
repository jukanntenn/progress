# CI / CD

English | [中文](ci-cd.zh.md)

GitHub Actions workflows under `.github/workflows/`:

- `ci.yml` — lint (ruff), type-check (ty), tests (unit/component/e2e, feed e2e included via Docker compose), frontend (lint/typecheck/test/build), drift checks (`scripts/check_drift.py` — deptry / import-linter / OpenAPI / TS types / i18n .pot + catalog / migrations), documentation gates (`scripts/doc_sync.py`), Docker build smoke. Runs on every push to `main` and every PR.
- `codeql.yml` — security analysis (Python).
- `release.yml` — multi-arch Docker image to GHCR **and Docker Hub** on `v*` tags (official login/metadata/build-push actions, native amd64+arm64 runners) + GitHub Release.
- `e2e.yml` — Playwright browser e2e against the production container; fires only when `src/`, `web/src/`, `docker/`, or `web/e2e/` change (docs-only edits do not trigger it).

Local parity: the drift and documentation steps run the exact commands available locally — `uv run python scripts/check_drift.py` and `uv run python scripts/doc_sync.py` — so a green local run predicts a green CI run.
