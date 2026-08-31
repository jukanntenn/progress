# PRFC: Documentation gates, corpus alignment, and local gating wiring

Status: implemented

[English](2026-08-22-documentation-gates-and-corpus-wiring.md) | 中文

## Problem

Markdown 语料没有任何机械检查:交叉链接静默腐烂,硬换行段落把 reflow 噪音塞进每一次 diff,`docs/` 里躺着叙述已完成迁移的时点性文档(`config-refactor.md`、`verification-config-refactor.md`),一份手工清单早已偏离现实(过时端口、已移除的 `truncate` provider、死链 `i18n.md`),CI 也不跑任何文档检查——drift job 覆盖的是生成物,不是行文。prek 全局 exclude 整体屏蔽 `^\.agents/`,决策记录树落地后将无人把关,其格式门禁会扫描零个文件而绿灯通过。commit message 按惯例使用 Conventional Commits——git log 一贯如此——但没有任何东西强制这个格式。

## Decision

**门禁。** `scripts/` 下的 stdlib-Python 门禁,共享 [`doclib.py`](../../../scripts/doclib.py) 中的掩码与 slug 辅助函数:[`verify_md_links.py`](../../../scripts/verify_md_links.py)(相对链接可解析,含 `#fragment` 锚点)、[`verify_md_wrap.py`](../../../scripts/verify_md_wrap.py)(一段一行;代码块、表格与列表保留其结构)、[`verify_md_current.py`](../../../scripts/verify_md_current.py)(README 与 docs 的现时态行文)、[`verify_prfc_format.py`](../../../scripts/verify_prfc_format.py)(随[树 PRFC](2026-08-22-prfcs-tree-and-contract.md) 落地)、[`verify_doc_budgets.py`](../../../scripts/verify_doc_budgets.py)(随[分层 PRFC](2026-08-22-layered-agent-instructions-and-mirrors.md) 落地)。[`doc_sync.py`](../../../scripts/doc_sync.py) 按序运行它们,保持每个可独立运行,并可将范围限定到给定的文件参数;staged 运行会把文件扩展到其双语配对。

**按本仓库校准的范围。** `verify_md_current` 覆盖 `README.md`、`README_zh.md` 与 `docs/*.md`——`specs/redesign/` 刻意不在范围内:其对比式文体(「旧→新」「不再用 X」)是 redesign 语料契约的一部分,且受编辑保护,而真正滋生陈旧叙事的是 `docs/`。禁词表刻意不含 `legacy`:旧版(pre-redesign)构建在这里是真实的产品词汇(`scripts/migrate_from_legacy.py`、一次性迁移指南)。links 与 wrap 覆盖 README、`PRINCIPLES.md`、根与 `web/AGENTS.md`、`docs/`、`specs/redesign/`、PRFC 树、`.agents/skills/`(仅 CI 全量——全局 exclude 使其不进 staged 运行)与 `web/e2e/`;CLAUDE.md 镜像是字节副本,依同一规则免检。

**接线。** prek 的 `doc-check` hook 只对 staged Markdown 运行 `doc_sync`——prek 在 hook 运行期间会 stash 未暂存的改动,更宽的扫描会看到陈旧的树——排除 `.zcode/` 镜像。prek 全局 exclude 从 `^\.agents/` 收窄为 `.agents/(skills|hooks)/`,PRFC 树及未来任何 `.agents/` 下的手写 Markdown 默认受门禁。CI 的 drift-checks job(更名 "Drift + docs checks")增加 `uv run python scripts/doc_sync.py`——`check_drift.py` 的「CI 与本地共享一条命令」原则从生成物延伸到行文。`check_drift.py` 本身保持纯粹的「再生成并 diff」;行文门禁是另一类,拥有自己的聚合器。

**commit-msg 门禁。** [`scripts/check_commit_msg.py`](../../../scripts/check_commit_msg.py) 加 prek `commit-msg` hook(`default_install_hook_types` 现已安装它),强制带可选 scope 的 Conventional Commits,与既有 log 风格及 `commit` skill 一致。

**语料对齐。** [`docs/AGENTS.md`](../../../docs/AGENTS.md) 是文档标准之家:分层图,每条规则链接其门禁;根 Standards 节指向这里。时点性文档逐文件处置:`config-refactor.md` 与 `verification-config-refactor.md` 删除,其经得起时间的决策由 [config PRFC](2026-06-26-config-database-single-source.md) 承载;`manual-verification-checklist.md` 是活的操作性内容,保留并修正其陈旧事实(端口 5000/3000 → 8000/5173、已移除的 `truncate` provider → 留空 `analysis.api_key`、死链 `i18n.md` → `specs/redesign/11-i18n.md`)。硬换行语料在同批变更中归一化(段落解开为一段一行)。双语范围仅限 PRFC 树;更广的语料在触发信号——文档开始以中文常态撰写——时配对,并届时另立记录。在那一天之前 `README_xh.md` 保留其名。

## Alternatives considered

**移植参照项目的文档流水线——TS/mdast 文档类型检查、i18n manifests、覆盖所有文档的词数预算、依赖图门控调度器。** 败因:仓库根没有 Node 工具链,语料是几十个文件而非几百个;stdlib 门禁秒级跑完,而 prek 加 `check_drift.py` 已是这里既定的聚合模式。

**只有规则没有门禁。** 败因:无纪律的漂移正是门禁存在的理由;标准里每条规则都点名执行它的门禁——没有机器支撑的规则只会把它禁止的失败重新制造一遍。

**把门禁折叠进 `check_drift.py`。** 败因:该脚本的契约是对生成物的非破坏性「再生成并 diff」;行文 lint 既非再生成也非 diff。每类一个聚合器,CI 以同一方式调用两者。

**按提案所述用 current-state 检查 `specs/redesign/`。** 实施时落选:扫描显示 specs 的命中是对比式设计语言(「bleach 已废弃,nh3 是替代」「换 aiohttp,requests 不再用」),不是陈旧叙事——redesign 语料依契约叙述迁移本身,强行改写只会让受编辑保护的设计文档为近乎零的价值翻腾。范围适配记录于上文,而非给提案措辞打掩护。

**现在就全面双语。** 败因:约三十五个文件的一次性翻译加上永久的配对义务,其中十八篇是受编辑保护的 specs——翻译即编辑;参照项目分两步依触发信号采纳配对,本记录沿用同一顺序。

**保留全局 `^\.agents/` exclude。** 败因:目录树落地后无人把关,格式门禁对零个文件绿灯通过——执行对等是门禁存在的理由。

## Consequences

`doc_sync` 对全语料绿灯(links 与 wrap 检查 63 个文件,current-state 检查 15 个,格式检查 8 个 PRFC 文件,预算 4 个);每道门禁都在手工样例上演练过——死链、reflow 的段落、历史叙事、写坏的记录、非 conventional 的提交主题——修复前失败、修复后通过。归一化机械地解开了十四个文件的段落;第一版一次性 reflow 脚本与门禁的掩码逻辑不一致(它吃掉了标记行内代码的反引号,还把一份 SKILL.md 的 YAML frontmatter 行接到一起)——修复方式是让 reflow 直接从门禁自身的掩码函数推导,并从当时尚干净的镜像恢复文件,这是「一次性工具必须导入门禁逻辑而非近似它」的实证。接受的代价:全语料真相在 CI,本地 hook 只查 staged 文件(与参照项目记录在案的同一取舍);current-state 的误报以在门禁范围清单中逐文件豁免救济,理由随附;`.agents/skills/` 的行文仅由 CI 全量把关,因为保护镜像免受改动型 hook 的全局 exclude 同时也使其不进 staged 文档运行。
