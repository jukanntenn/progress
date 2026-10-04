# RFC: Layered agent instructions, direction-free mirrors, and single-source skills

Status: implemented

[English](2026-08-22-layered-agent-instructions-and-mirrors.md) | 中文

## Problem

根 `AGENTS.md` 以 2,173 词加载进每一个 agent session:前端命令、Playwright e2e 说明、CI 工作流清单、用户管理与迁移流程——这些本应归于 docs 层的操作性细节——与真正的常驻指令并排而坐,且没有任何机械手段约束该文件的增长(参照项目自己的记录证明:没有预算兜底,行文纪律必然失守)。`CLAUDE.md` 声称「逐字镜像 AGENTS.md」,背后没有任何工具支撑这句话——而且这句话在 HEAD 里就已经不实:已提交的配对互相不一致(缺一段 shipping 说明、一行过时的 `release.yml` 描述)。skills 以两份人工镜像存在——`.agents/skills/`(8 个)与 `.zcode/skills/`(7 个)——没有声明的单一来源也没有门禁;漂移已经发生:`grilling-sleek` 只存在于 `.agents` 一侧。

## Decision

**无方向指令镜像。** [scripts/agentlib.py](../../../../scripts/agentlib.py) 对每个配对以 git HEAD 判方向——绝不用 mtime,clone 与 checkout 会把它重置:恰好一侧与 HEAD 不同,则该侧复制覆盖另一侧,新鲜更新陈旧;两侧相同即通过;两侧都改且互不一致是冲突,工具拒绝猜测。HEAD 中不存在的路径计为其侧已变更,新配对由此自举。[scripts/check_agent_instructions.py](../../../../scripts/check_agent_instructions.py) 是门禁(自愈:复制新鲜一侧并 stage 陈旧镜像),[scripts/sync_agent_instructions.py](../../../../scripts/sync_agent_instructions.py) 是修复器;prek 的 `agent-instructions-sync` hook 在提交时运行门禁。

**镜像矩阵。** 根 `AGENTS.md` ↔ `CLAUDE.md` 与 `web/AGENTS.md` ↔ `web/CLAUDE.md` 是无方向配对。skills 单一来源:`.agents/skills/` 是源(agents.md 生态的标准路径,且已是超集),单向镜像到 `.zcode/skills/`——一个工具专属的加载路径;单向,因为副本的镜像不是对等的配对;门禁按文件报告镜像漂移并点名单一来源,绝不猜测。同一个 agentlib 承载两种模式。

**带预算的分层。** 根文件保留每个 session 都需要的东西——身份、技术栈、布局图、命令索引、Standards 指针、Boundaries、Testing/CI 摘要、PRFCs 节,以及一节 "Editing these instructions" 陈述镜像契约与预算——并甩掉子树与操作性细节:前端命令、前端技术栈条目与 Playwright e2e 块移入新的 [web/AGENTS.md](../../../../web/AGENTS.md);Users、Proposal Tracking、Database Migrations、CI/CD 各节压缩为指向 docs 层的指针(新页 [docs/users.md](../../../../docs/users.zh.md) 与 [docs/ci-cd.md](../../../../docs/ci-cd.zh.md) 承接细节)。词数上限存于 `scripts/doc_budgets.manifest.json`,由 `scripts/verify_doc_budgets.py` 门禁;被预算的文件失踪即失败。上限按拆分后内容加余量设定——根文件以 `wc -w` 计落在 2,066 词,上限 2,300(提案阶段 1,400–1,500 的估计低估了布局图,它正当留在根里);`web/AGENTS.md` 235 词上限 300;`docs/AGENTS.md` 上限 600;`.agents/prfcs/AGENTS.md` 上限 150。

`PRINCIPLES.md` 保持活的价值观之家。参照项目将其对应文件冻结为归档,但 progress 的 skills 把该文件当作操作性价值观(`iterating` skill 直接点名引用);适配的这一部分刻意不移植。

## Alternatives considered

**symlink 镜像——参照项目的机制。** 构造上零漂移,但 git 把 symlink 存为持有目标路径的 blob,Windows 检出在未开 `core.symlinks=true` 时会把 `CLAUDE.md` 物化成一个内容为九个字节文本的普通文件;没有任何东西把贡献者约束在类 Unix 检出上。败因与参照适配中落选时相同。

**保留单个大根文件。** 每个 session 为不需要的细节付费,且没有机械预算则增生不止——加载路径早已支持渐进披露(工具沿 cwd 链合并子树指令文件),分层把上下文税局部化。

**照参照项目的激进程度按栈拆分(后端或 `src/progress/integrations/` 的子树 AGENTS.md)。** 参照项目是三个工作区里的四个技术栈;progress 的后端是单个 Python 包,其 integration 插件规则已住在根布局图与 spec 06 里。后端子树文件只会复述根文件——正是分层体系要猎杀的 slop。触发信号后复议:integrations 的写作成为高频日常之时。

**AGENTS/CLAUDE 配对用方向性同步。** 方向性本身就是缺陷,不是可调参数:被命名为次级的一侧,其编辑会被修复器静默回滚,而那一侧恰恰是其工具加载它、其 agent 最可能编辑它的一侧。

**以 mtime 判方向。** clone 与 checkout 把 mtime 重置为现在,两侧同等新鲜;对 HEAD 的内容比较是确定性的,不依赖任何文件系统状态。

**每工具的原生规则文件(`.cursor/rules` 之流)。** 一个事实在每个工具里各得一个家,然后在彼此间漂移;镜像让同一份内容以每工具的文件名存在,边际创作成本为零。

## Consequences

镜像矩阵经直接演练:任一侧的单侧编辑被检出并修复(门禁复制并 stage 陈旧镜像),两侧相同编辑通过,互不一致的编辑失败并点名两侧与和解步骤,新增配对的一侧自举出另一侧——`web/` 配对正是这样落地的。落地同时修复了 Problem 一节点名的两处既有漂移:根 `CLAUDE.md` 追上了重写后的 `AGENTS.md`,`grilling-sleek` 到达了 `.zcode/skills/` 镜像。接受的代价:hook 会改动 staged 内容,限定在确定性的「恰好一侧变更」场景(双侧永不猜测);根文件在预算之下坦然携带布局图而非人为压缩——预算是上限不是目标,提升上限须带理由的清单 diff;直接编辑 `.zcode/skills/` 会被设计如此地覆盖,门禁的错误输出会点名单一来源,读到它的 agent 知道该去哪里编辑。
