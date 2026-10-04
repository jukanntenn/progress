# CI / CD

[English](ci-cd.md) | 中文

`.github/workflows/` 下的 GitHub Actions 工作流：

- `ci.yml` —— lint（ruff）、类型检查（ty）、测试（unit/component/e2e，feed e2e 经 Docker compose 纳入）、前端（lint/类型检查/测试/构建）、漂移检查（`scripts/check_drift.py` —— deptry / import-linter / OpenAPI / TS types / i18n .pot + catalog / migrations）、文档门禁（`scripts/doc_sync.py`）、Docker 构建冒烟测试。每次推送到 `main` 以及每个 PR（Pull Request）都会运行。
- `codeql.yml` —— 安全分析（Python）。
- `release.yml` —— 在 `v*` 标签上向 GHCR **与 Docker Hub** 发布多架构 Docker 镜像（官方 login/metadata/build-push actions、原生 amd64+arm64 运行器），并创建 GitHub Release。
- `e2e.yml` —— 针对生产容器的 Playwright 浏览器 e2e；仅在 `src/`、`web/src/`、`docker/` 或 `web/e2e/` 变更时触发（纯文档改动不触发）。

本地对等：漂移与文档门禁步骤运行的就是本地可用的那几条命令 —— `uv run python scripts/check_drift.py` 与 `uv run python scripts/doc_sync.py` —— 因此本地通过即可预判 CI 通过。
