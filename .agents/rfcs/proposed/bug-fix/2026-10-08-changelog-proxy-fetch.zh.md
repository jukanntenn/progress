# RFC: changelog 拉取的 per-tracker 代理路由

Status: proposed

[English](2026-10-08-changelog-proxy-fetch.md) | 中文

## 问题

Changelog tracker 通过共享的 aiohttp session 拉取任意 URL。[spec 07 的 HTTP 客户端重构](../../../../specs/redesign/07-git-http-clients.md)之后，该 session 以 `trust_env=False` 创建、自身永不做代理：配置的代理（`core.github.proxy`）只被逐请求地注入 GitHub 客户端、git 子进程，以及沿用该先例的 v2ex 客户端。Changelog 的 `_fetch_text` 不传 `proxy=`，于是每一个「不走代理就不可达」的 tracker 每次检查都失败，而单个 tracker 失败就会把整个 integration 降级为 `partial`/`failed`。[changelog spec](../../../../specs/integrations/changelog.md) 此前仍记载着重构前的假设（「代理依赖共享 ClientSession 的环境变量配置」），这条被切断的路径因此从未被发现。已部署的 tracker 集合混合了直连可达的 URL（u-tools.cn、zcode.z.ai）与必须走代理的 URL（raw.githubusercontent.com），「全部走代理」与「全部直连」都不正确。

## 方案

### Per-tracker 选择启用，单一代理配置源

`ChangelogItemConfig`——以及 `sync` 镜像到的 `ChangelogTracker` 行——新增 `use_proxy: bool = false`。`use_proxy = true` 的 tracker，其拉取请求以 per-request `proxy=` 参数携带 `core.github.proxy`，即 GitHub 客户端与 v2ex 已在消费的同一个配置项；不新增代理 URL 字段，也就没有会失同步的第二份配置。默认 `false` 使升级后所有存量 tracker 行为逐字节不变：代理只作用于用户明确要求的地方。

### 半配置状态显式失败

`use_proxy = true` 而 `core.github.proxy` 为空时，该 tracker 的检查直接返回 `failed`，错误信息指明缺失的配置项，且不发起任何请求。静默回退直连只会复刻今天那种不透明的超时失败——那正是本次修改要消除的困惑。

### 其余全部复用既有机制

设置界面从 section schema 自动渲染该字段；`sync` 像 `enabled`/`parser_type` 一样把它镜像到行上；一个迁移增加一列布尔值；per-request 代理是 aiohttp 3.10 的既定模式（`ProxiedGitHubAPI`、`V2exClient`），共享 session 保持 `trust_env=False`，Feishu/MarkPost/AI/Miniflux 流量继续直连。

## 已考虑的替代方案

**所有 changelog 拉取整体走 `core.github.proxy`（v2ex 式全量代理）。** v2ex 的流量是单一被整体封锁的站点；changelog 的 tracker 列表天然异构，且已部署集合混合了直连可达与仅代理可达的 URL。全量代理会新引入「代理必须能到达每个 tracker 主机」的依赖，让当前正常工作的 tracker 也面临回归，且没有任何按 tracker 的退路。

**per-tracker 代理 URL 字段。** 把部署环境里唯一的一个代理 URL 复制进 N 个 tracker 条目——同一事实的第二事实源；v2ex 已确立 `core.github.proxy` 是项目唯一的代理配置项。

**读取 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量（`trust_env=True`）。** spec 07 已否决：这会拖拽进程内所有 HTTP 客户端——Feishu、MarkPost、AI、Miniflux——经过为封锁外网流量准备的代理；逐请求透传才是把代理限定在需要它的请求上的受支持方式。

**对知名被封锁域名自动走代理。** 可达性是部署环境的事实，用户知道而进程无法验证；硬编码域名列表是配置无法覆盖的魔法启发式。

## 验收标准

- `use_proxy = true` 且 `core.github.proxy` 非空：该 tracker 的拉取请求携带 `proxy=<配置的代理>`；检查行为其余不变。
- 默认 `use_proxy = false`：即使配置了代理，该 tracker 也直连拉取。
- `use_proxy = true` 而 `core.github.proxy` 为空：该 tracker 的检查返回 `failed`，错误信息指明 `core.github.proxy`；不发起请求；其他 tracker 不受影响。
- 缺少该键的存量 DB 配置行加载行为不变（`false`）；`sync` 把 `use_proxy` 的变化镜像到行上，不触碰水位。
- 设置界面仅凭 section schema 就能在 changelog 分节渲染出该开关。

## 风险

- 被启用代理的 tracker 主机必须**经由代理**可达；代理若封锁它，只是把直连超时换成经代理的错误。无论哪种情况，既有的拉取错误路径都会给出 tracker 名称与 URL。
- 代理 URL 在检查时从 integration 持有的 `CoreConfig` 解析——与 repo/proposal/v2ex 客户端相同的时效语义，不是新增缓存。
- 行上多了一个镜像布尔值：config 与行之间的分歧由 sync 比较逻辑和 CI 迁移 drift 门禁约束。
