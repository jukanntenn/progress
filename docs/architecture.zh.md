# progress 架构

[English](architecture.md) | 中文

改动源码树之前先读本文。它是代码库的有序地图——组件、边界、以及新行为的归属；决策理由在链接的 RFC（决策记录）里。

## 这个包是什么

progress 是一个 GitHub 项目跟踪工具：追踪多仓库代码变更、对其运行 AI 分析，并为用户关注的开源项目生成进展报告（Web UI、RSS、通知）。运维者通过 `progress` CLI 按计划运行流水线，经 FastAPI 驱动的 SPA 阅读结果。

## 组件

| 组件 | 职责 | 公共接口 |
|---|---|---|
| `src/progress/config/` | 分层配置源 + 数据库种子合并 | `progress.config.CoreConfig` |
| `src/progress/db/` | Tortoise 模型与共享迁移 | `init_db` / `close_db` |
| `src/progress/integrations/` | 业务插件，一包一集成（repo、changelog、proposal、feed、v2ex） | `@register("<name>")` |
| `src/progress/kernel/` | cordis-semantics 插件内核（fiber、事件、补丁） | `boot` / `Entry` / `Context` |
| `src/progress/runtime/` | 应用自身的插件与组装 | `compose_serve` / `compose_base` |
| `src/progress/observability/` | OTel + structlog + Bugsink 接线 | `setup_observability` |
| `src/progress/utils/` | 纯工具函数（http、模板、markdown、i18n） | — |
| `src/progress/cli/` | Typer 入口：run/serve/users/plugin 及报告、通知、AI | `progress` 命令 |
| `src/progress/api/` | FastAPI 入口包（路由、依赖、中间件） | `create_app` |
| `web/` | 消费 OpenAPI schema 的 React 19 + Vite SPA | HTTP `/api` |
| `docker/`、`devops/` | 双进程容器；ansible 部署 | — |

## 新行为的归属

新集成为 `src/progress/integrations/<name>/` 下的自包含包，经 `@register` 注册；新配置项从 `src/progress/config/schema.py` 开始（随后重新生成 OpenAPI 契约）；新模型放 `src/progress/db/models/` 并附迁移；新 HTTP 路由放 `src/progress/api/routes/`；报告模板或通知渠道放 `src/progress/cli/reports/` 或 `cli/notifications/channels/`。Agent 工作流指引放 `.agents/skills/`，决策理由按 [RFC 规则](../.agents/rfcs/README.zh.md)放 `.agents/rfcs/`。文档放置规则见[文档标准](AGENTS.md)，配对契约见[双语文档契约](i18n/README.zh.md)。

贡献者入口见 [development.zh.md](development.zh.md)。
