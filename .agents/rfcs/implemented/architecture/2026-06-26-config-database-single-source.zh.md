# RFC: Configuration lives in the database; the TOML file is a one-time seed

Status: implemented

[English](2026-06-26-config-database-single-source.md) | 中文

## Problem

Progress 曾经把一切配置都放在单个可写的 `config.toml` 里并挂载进容器,这个形态失败了两次。Web UI 通过 `POST /config` 改写该文件,而 Ansible 用 `config.toml.j2` 模板化它,于是每次重新部署都会把用户在 UI 里做的修改静默清掉——部署流水线与运行时争夺同一个文件。复杂的列表配置——`repos`、`owners`、`notification.channels`、`changelog_trackers`、`proposal_trackers`——全部以 TOML 声明,越涨越大且难以维护。次要的坏味道:web 配置编辑器由 `src/progress/api/routes/config.py` 里一份 665 行手写 schema 驱动,复刻了 pydantic 模型——一张表单两个真相源。

## Decision

**数据库是应用配置的单一真相源。** TOML 文件是一次性种子加基础设施配置的提供者;首次运行之后,文件里的应用配置即被忽略,文件↔DB 之间的跨越是显式动作(`progress config import` / `export`)。

**文件与环境只保留真正的引导配置**——`data_dir`、`workspace_dir`、db 路径、server bind/port、调度 cron、日志级别——即打开数据库之前就必须拿到的键。其余一切(含 `gh_token`、channels、repos、analysis)住在数据库里,经 web UI 依从 pydantic 模型生成的 JSON Schema(`get_config_json_schema()`)编辑,手写 schema 的复刻就此关闭。

**DB 存储是混合的:** 标量与嵌套配置存进单个带版本的 JSON blob(`app_config` 表,带乐观锁版本与读取时的秘密掩码);`repos` 与 `owners` 留在其既有结构化表(`repositories` / `github_owners`)中——它们本来就承载运行时状态(`last_commit_hash`、`last_check_time`)。

**Ansible 只管 docker-compose、首次部署的 infra/seed TOML 与 secrets/vault**——重跑它永远不可能覆盖运行时配置,因为应用在播种之后即忽略文件里的应用配置。

## Alternatives considered

**保留可写的 TOML 文件并协调写入方。** 败因:Ansible↔UI 的冲突是一个文件两个主人的固有产物;给部署排队或加锁,是把分布式系统的问题搬进一个单一源设计本可直接消除它的地方。

**把引导配置也搬进 DB。** 败因:鸡生蛋——打开数据库之前就需要 db 路径与 bind 地址;文件/环境里保留引导子集是能存在的最小集。

**每个配置键一行,替代带版本的 blob。** 败因:标量/嵌套配置没有逐键的运行时状态,逐键行买不到任何查询能力,却让迁移面成倍增长;`repos`/`owners` 保留结构化表,恰恰因为它们承载运行时状态。

## Consequences

配置编辑器从生成的 JSON Schema 渲染(与 pydantic 模型同一真相源);UI 编辑带乐观锁地持久化到 DB(版本过期 → HTTP 409),秘密往返时掩码,重启永远不会重新播种已存在的 DB。该重构的时点性文档(`docs/config-refactor.md`、`docs/verification-config-refactor.md`)在本记录承载了持久 why 之后删除;现时状态细节住在 `specs/redesign/02-config-system.md` 与 `docs/config.md`。
