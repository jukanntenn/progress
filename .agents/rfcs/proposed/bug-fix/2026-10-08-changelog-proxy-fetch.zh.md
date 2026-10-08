# RFC: changelog 拉取的 per-tracker 代理路由

Status: proposed

[English](2026-10-08-changelog-proxy-fetch.md) | 中文

## 问题

Changelog tracker 通过共享的 aiohttp session 拉取任意 URL。[spec 07 的 HTTP 客户端重构](../../../../specs/redesign/07-git-http-clients.md)之后，该 session 以 `trust_env=False` 创建、自身永不做代理：配置的代理（`core.github.proxy`）只被逐请求地注入 GitHub 客户端、git 子进程，以及沿用该先例的 v2ex 客户端。Changelog 的 `_fetch_text` 不传 `proxy=`，于是每一个「不走代理就不可达」的 tracker 每次检查都失败，而单个 tracker 失败就会把整个 integration 降级为 `partial`/`failed`。[changelog spec](../../../../specs/integrations/changelog.md) 此前仍记载着重构前的假设（「代理依赖共享 ClientSession 的环境变量配置」），这条被切断的路径因此从未被发现。已部署的 tracker 集合混合了直连可达的 URL（u-tools.cn、zcode.z.ai）与必须走代理的 URL（raw.githubusercontent.com），「全部走代理」与「全部直连」都不正确。

## 方案

### Per-tracker 代理 URL，与 GitHub 代理解耦

`ChangelogItemConfig`——以及 `sync` 镜像到的 `ChangelogTracker` 行——新增 `proxy: str = ""`。非空值即该 tracker 拉取使用的 HTTP(S) 代理 URL，以 per-request `proxy=` 参数透传；空（默认）直连。该字段与 `core.github.proxy` 相互独立：GitHub 代理服务的是 GitHub/git/v2ex 流量，而 changelog 的 URL 是任意主机、并非 GitHub 服务，应自带路由。默认空值使升级后所有存量 tracker 行为不变。

### 畸形 URL 在配置期失败

非空 `proxy` 必须以 `http://` 或 `https://` 开头；其他值（裸 `host:port`、HTTP 客户端无法使用的 `socks5://`）在配置校验时被拒绝——PUT 返回 422，存储的坏值在加载时回退默认并记录警告——而不是在运行中期以难解的 aiohttp 错误浮现。

### 其余全部复用既有机制

设置界面从 section schema 自动渲染该字段；`sync` 像 `enabled`/`parser_type` 一样把它镜像到行上；一个迁移增加一列 varchar；per-request 代理是 aiohttp 3.10 的既定模式（`ProxiedGitHubAPI`、`V2exClient`），共享 session 保持 `trust_env=False`，Feishu/MarkPost/AI/Miniflux 流量继续直连。

## 已考虑的替代方案

**通过 per-tracker `use_proxy` 布尔复用 `core.github.proxy`。** v2ex 先例让「单一共享配置项」看似足够，但 v2ex 的流量是单一被整体封锁的站点，而 changelog 列表是任意主机：把 changelog 拉取耦合到 GitHub 代理，会让 GitHub 的配置项对外来 URL 承担载荷，GitHub 代理的改动也会波及 changelog 行为。评审中因该耦合被否决。

**所有 changelog 拉取整体走 `core.github.proxy`（全量代理）。** 已部署集合混合了直连可达与仅代理可达的 URL；全量代理会新引入「代理必须能到达每个 tracker 主机」的依赖，让当前正常工作的 tracker 也面临回归，且没有按 tracker 的退路。

**读取 `HTTP_PROXY`/`HTTPS_PROXY` 环境变量（`trust_env=True`）。** spec 07 已否决：这会拖拽进程内所有 HTTP 客户端——Feishu、MarkPost、AI、Miniflux——经过为封锁外网流量准备的代理；逐请求透传才是把代理限定在需要它的请求上的受支持方式。

**对知名被封锁域名自动走代理。** 可达性是部署环境的事实，用户知道而进程无法验证；硬编码域名列表是配置无法覆盖的魔法启发式。

## 验收标准

- `proxy` 非空的 tracker：其拉取请求携带 `proxy=<该 URL>`；检查行为其余不变。
- `proxy` 为空的 tracker：即使配置了 `core.github.proxy` 也直连拉取。
- 不以 `http://`/`https://` 开头的 `proxy` 值：配置校验拒绝（PUT 返回 422）；存储的坏值加载时回退默认并记录警告。
- 缺少该键的存量 DB 配置行加载行为不变（`""`）；`sync` 把 `proxy` 的变化镜像到行上，不触碰水位。
- 设置界面仅凭 section schema 就能在 changelog 分节渲染出该字段。

## 风险

- tracker 的主机必须**经由其配置的代理**可达；代理若封锁它，会通过正常的拉取错误路径浮现，且错误仍带 tracker 名称与 URL。
- 行上多了一个镜像 varchar：config 与行之间的分歧由 sync 比较逻辑和 CI 迁移 drift 门禁约束。
- scheme 校验是唯一的静态检查；格式正确但内容错误的 URL（scheme 对、主机错）只能在拉取时暴露——与任何其他网络误配置的可见性相同。
