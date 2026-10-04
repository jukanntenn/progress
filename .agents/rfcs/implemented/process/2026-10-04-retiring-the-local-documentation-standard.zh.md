# RFC: 为 hdsh harness 退役本地文档标准

Status: implemented

[English](2026-10-04-retiring-the-local-documentation-standard.md) | 中文

## 问题

progress 此前有自带的文档标准：`doc_sync.py` 聚合五个 `verify_*.py` 门禁、词数天花板放在 `scripts/doc_budgets.manifest.json`、决策记录放在 `.agents/prfcs/`、README 采用 `README.md`/`README_zh.md` 命名约定。在它旁边再采纳 hdsh harness 等于对同一语料跑两套门禁：本地 wrap 门禁会把 `<!-- hdsh:slot -->` 标记注释当作正文解析，本地配对范围表达不了 `README.zh.md` 三件套，两棵决策记录树也违反 harness 装入的「一个事实一个家」规则。harness 的采纳手册要求在同一次采纳中完成退役，而不是并行双标准。

## 决策

本地标准在采纳 harness 的同一变更中退役。`scripts/doc_sync.py`、五个 `verify_*.py` 门禁、`doclib.py` 与 `scripts/doc_budgets.manifest.json` 连同 prek `doc-check` 钩子和运行它们的 CI 步骤一起删除；由 hdsh 门禁（配对、RFC 格式、wrap、链接、词数、采纳完成度）取而代之，进入 prek 的 `hdsh` 组，并在 CI 中钉在采纳的 ref 上。六个 implemented PRFC 对从 `.agents/prfcs/implemented/` 迁入 `.agents/rfcs/implemented/{architecture,process}/`，头部改写为 RFC 格式并补齐 `.i18n.yaml` 记录，成为完整三件套。词数天花板折入 `.hdsh/docs.manifest.json`：`AGENTS.md` 2600 与 `docs/AGENTS.md` 1100 吸收 harness 合并带来的常备指令与文档标准增长并保留 5% 余量；`docs/development.md` 从模板的 300 提到 900，因为现存 851 词的贡献者指南仍是权威文档；`web/AGENTS.md` 维持 300。`README_zh.md` 更名 `README.zh.md` 并记录为 `README.md` 的配对副本，整个 `docs/` 语料在配对契约下补齐中文副本。

## 备选方案

**双标准并行。** 零迁移成本，但 harness 明令禁止：本地 wrap 门禁与移植来的 slot 标记注释互相打架，每条规则存在两份且细节略有出入——这正是门禁要消灭的漂移。

**保留 `.agents/prfcs/` 与 `.agents/rfcs/` 并存。** 违反一个事实一个家：两棵决策树意味着两个可 grep 的清单、两种要执行的格式，而 PRFC 格式门禁本身就是退役标准的一部分。

## 后果

- hdsh 门禁成为唯一的文档门禁；升级在新 ref 下重跑 `hdsh adopt apply`，改动向上游回流。
- 退役门禁的名字（`doc_sync`、`verify_md_*`、`verify_prfc_format`）只存在于 git 历史与当初裁决它们的记录正文里。
- 上述天花板上调即词数门禁要求的理由；此后上调遵循先搬迁、再压缩、最后上调的次序。
- 采纳前的记录 `2026-08-22-prfcs-tree-and-contract.md` 描述的是退役的 `.agents/prfcs` 树；现在决策住在何处由本记录而非那份记录裁决。
