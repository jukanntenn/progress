# RFC: The .agents/prfcs tree and its contract

Status: implemented

[English](2026-08-22-prfcs-tree-and-contract.md) | 中文

## Problem

progress 里没有决策依据的安身之处。`specs/redesign/00-17` 是权威设计契约——描述现状、系统是什么——且受编辑保护(根 `AGENTS.md` 的 "Ask first");`PRINCIPLES.md` 承载行为价值观而非决策;commit message 与 git 历史无法把一个决策带过后来触碰它的那些变更。结果正是 RFC 体系要防止的失败:设计为何如此只活在记忆里,输掉的备选方案被从头重新争论,reviewer 不做考古就回答不了「为什么不用 X」。参照适配——markpost 的 `.agents/mrfcs/`,其本身适配自 deepseek-harness 的 agent notes——已在同等规模上验证了该机制,且以「选择性移植」为立身裁决。

## Decision

PRFC——progress 的 RFC:持久化的提案与决策记录,承载_为什么_、输掉的备选方案、以及代码和 specs 装不下的部分——存放于 `.agents/prfcs/{proposed,implemented,rejected}/yyyy-mm-dd-topic-title.md`;日期为该话题依 git 历史首次提出之日。目录树本身就是清单:浏览或 grep 仓库即可,没有索引文件。

两份文档以正交分工承载契约:`README.md` 是规范契约(布局、生命周期、文件格式),附 [`README.zh.md`](../../README.zh.md) 镜像;[`AGENTS.md`](../../AGENTS.md) 只放常驻指令——写前先 grep 找既有归属、禁止把一条记录改写成另一个决策、保持配对同步——每条都是指向其规则之家的触发器。

文件格式由 `scripts/verify_prfc_format.py` 强制执行,stdlib Python。头部块固定为 `# PRFC: <title>` 与 `Status: <status>`;status 与所在目录一致(`proposed`、`implemented` 或 `rejected — <一行理由>`);正文以 `## Problem` 开篇,须脱离解决方案仍能成立。`proposed/` 接续 `## Proposal` … `## Alternatives considered` … `## Acceptance criteria` … `## Risks`。`implemented/` 接续 `## Decision`(现在时,路径与名称与今日代码一致)… `## Alternatives considered` … `## Consequences`。`rejected/` 冻结其提案期骨架;裁决写在 `Status:` 行上。`## Alternatives considered` 在每条记录中强制——每个真实备选方案一段加粗开头的段落及其败因,按当时实际论证记录,绝不事后编造。文件在目录间移动,须在同一次变更中更新其 `Status:` 并重新满足目标目录的骨架。

每条记录都是双语配对:`foo.md` 与 `foo.zh.md` 并列,骨架相同,机器 token 与章节标题保留英文,头部携带链接镜像的语言切换行,两者同步更新。记录内的相对链接必须可解析;指向尚不存在之物的引用以代码字面量书写,落地它的那次变更将其转为链接。

与 `specs/redesign/` 的边界:specs 描述是什么——设计契约,受编辑保护;PRFC 记录为什么、放弃了什么。互不复述,彼此链接。

触发规则:每个非平凡变更在同一次 PR 中新增或更新至少一条 PRFC——非平凡指变更触及行为、架构、跨文件契约、工具链、测试策略、on-disk 或 wire 格式,即维护者可能合理复议的任何东西。纯机械或局部编辑豁免。更新已拥有该决策的 PRFC 即满足规则;动笔前先 grep `.agents/prfcs/`。

prek 全局 exclude 已收窄为 `.agents/(skills|hooks)/`(见[门禁 PRFC](2026-08-22-documentation-gates-and-corpus-wiring.zh.md)),目录树由此在提交时与 CI 中均受门禁。

## Alternatives considered

**整体照搬 deepseek-harness——class 子目录(feature/bug-fix/simplification/architecture/process/testing)、带 sidecar 哈希的冻结密封归档、每条记录 `.md` + `.zh.md` + `.i18n.yaml` 三件套、每个 lifecycle 目录各配 AGENTS.md。** 败因:markpost 的奠基裁决已为「比参照仓库小一个数量级的语料」拒绝了它,而 progress 的语料起始更小;三件套与清单的维护税每一次编辑都要付,在此规模下买不到任何东西。零件只随触发信号到来,绝不整批搬运。

**ADR 惯例(`docs/adr/`)。** 败因:本语料在写作与阅读两端都是 agent 优先;`.agents/` 是 agent 工具既有的加载路径(今天是 skills,现在加上 PRFC),决策记忆应当挨着消费它的那些工作流。

**把决策记进 `specs/redesign/` 正文。** 败因:specs 是受编辑保护的现时状态契约;把设计依据折叠进去会让「是什么」与「为何是」混杂,而编辑保护使日常决策无处落笔、落笔就要走一遍评审仪式。

**生成式索引文件。** 败因:生命周期目录树就是清单,grep 就是检索;索引是第二份必须保持同步的真相。

## Consequences

目录树与其 README 配对、`AGENTS.md`、格式门禁一次变更落地;门禁对全树通过,包括本记录的配对;一条故意写坏的记录(缺镜像、status 错误、`implemented/` 里出现提案期标题)会使其失败——已手工演练并还原。CI 与本地运行同一条命令(`uv run python scripts/doc_sync.py`,见[门禁 PRFC](2026-08-22-documentation-gates-and-corpus-wiring.zh.md))。本记录与另两条姊妹记录自举了生命周期:以 `proposed/` 配对起草、评审、实施,再于同批变更移入并改写为 `implemented/` 骨架——机制亲自演练了自身的引入。接受的代价:每个非平凡变更都要携带新记录或更新记录(豁免条款与 grep 先行让义务与规模相称);每次记录更新要同时触碰配对的两种语言——维护者以中文工作,镜像是特性而非附加费;格式门禁可能误判,届时门禁的变更与促成它的需求同批交付并在此说明。[config PRFC](../architecture/2026-06-26-config-database-single-source.zh.md) 从一份已删除的时点性文档回填了 2026-06 配置重构的持久 why——这是[门禁 PRFC](2026-08-22-documentation-gates-and-corpus-wiring.zh.md) 下处置时点文档的范式。
