# Progress Request for Comments (PRFC)

[English](README.md) | 中文

PRFC 是 progress 的 RFC:持久化的提案与决策记录——承载_为什么_、_放弃了什么_、以及代码与 specs 装不下的部分。Specs 描述现状;PRFC 解释现状为何如此。

<a id="layout-and-naming"></a>

## 布局与命名

每条 PRFC 存放于 `.agents/prfcs/{lifecycle}/yyyy-mm-dd-topic-title.md`。日期为该话题首次提出之日(依 git 历史)。生命周期目录树本身就是清单——浏览或 grep 仓库即可;没有需要维护的索引文件。

- **`proposed/`**——实施前接受评审的提案。尚未构建,或仅部分构建。
- **`implemented/`**——已交付的决策。文件以现在时记录决定了什么、拒绝了什么。当代码后来重命名文件或修改默认值时,在同一次变更中更新 PRFC 的事实(路径、名称、结构)——但绝不能把它改写成另一个决策;用新 PRFC 取代并交叉链接两者。
- **`rejected/`**——提案经考虑后被否决。仅当其理由能防止一个有诱惑力的错误时保留;否则删除。

PRFC 之间的交叉引用使用相对 Markdown 链接,绝不用裸文字,这样 [`verify_md_links`](../../scripts/verify_md_links.py) 能检查它们,且在目录间移动后仍然有效。

<a id="when-to-write-one"></a>

## 何时撰写

每个非平凡变更在同一次 PR 中新增或更新至少一条 PRFC。非平凡指变更触及行为、架构、跨文件契约、工具链、测试策略、on-disk 或 wire 格式,或维护者可能合理复议的任何东西。纯机械或局部编辑豁免。更新已拥有该决策的 PRFC 即满足规则——不要创建重复;动笔前先 grep `.agents/prfcs/`。

<a id="the-file-format"></a>

## 文件格式

头部块固定为:

```markdown
# PRFC: <title>

Status: <status>
```

`Status:` 的取值必须与所在目录一致,共三种形式:`proposed`、`implemented` 或 `rejected — <一行理由>`(拒绝理由是读者要找的事实)。正文以 `## Problem` 开篇,须脱离解决方案仍能成立。

`implemented/` 接续 `## Decision`(现在时,交付了什么)… `## Alternatives considered` … `## Consequences`。提案期标题——`## Proposal`、`## Plan`、`## Migration plan`、`## Acceptance criteria`——被格式门禁在此拒绝。

`proposed/` 接续 `## Proposal` … `## Alternatives considered` … `## Acceptance criteria` … `## Risks`。工作未建之时,提案可以用将来时。

`rejected/` 冻结其提案期的任何章节;裁决写在 `Status:` 行上。

每条记录都是双语配对:英文原文 `foo.md` 旁附 `.zh.md` 镜像——骨架相同,机器 token 与章节标题保留英文,头部携带链接镜像的语言切换行——两者同步更新([树契约 PRFC](./implemented/2026-08-22-prfcs-tree-and-contract.md))。

**`## Alternatives considered` 在每条 PRFC 中强制**——每个真实备选方案一段加粗开头的段落及其败因。没有记录手下败将的决策会招致反复翻案,那正是 PRFC 要防止的失败。备选方案按当时论证如实记录,绝不事后编造。

文件在生命周期目录间移动,须在同一次变更中更新其 `Status:` 并重新满足目标目录的骨架,配对的两种语言同步:`proposed/` → `implemented/` 把 `## Proposal` 改写为现在时的 `## Decision`,并把 `## Acceptance criteria`/`## Risks` 折叠进 `## Consequences`;`proposed/` → `rejected/` 只在 `Status:` 上追加理由并冻结文件。

[`verify_prfc_format.py`](../../scripts/verify_prfc_format.py) 强制执行以上全部;它作为 [`doc_sync.py`](../../scripts/doc_sync.py) 的一部分运行。
