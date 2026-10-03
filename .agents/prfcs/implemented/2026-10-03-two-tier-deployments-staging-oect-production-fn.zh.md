# PRFC: Two deployment tiers — oect as staging, fn as production

Status: implemented

[English](2026-10-03-two-tier-deployments-staging-oect-production-fn.md) | 中文

## Problem

inventory 里 `fn` 所在组名为 `test`（dogfooding），而 `prod` 组是为一个始终未落地的生产主机预留的占位。实际情形是：`fn` 的 dogfooding 部署早已成为长期稳定、携带数据的正式服务——组名与"哪台机器真正重要"的事实相反，且每个本地构建出的镜像都直接发到 `fn`，等于每次都拿未验证的变更直接上生产。同时也不存在一个可以放心搞坏的快速验证环境。占位 `prod` 槽位指向 `oect`（192.168.5.50，arm64），正是同时承载内网 registry 的那台机器。

## Decision

**两个命名层级：`staging` = `oect`，用于快速迭代与新镜像验收；`prod` = `fn`，承载稳定服务，仅在变更于 staging 验收通过后才更新。** 晋级只发生在命名与默认值上，绝不触碰正在运行的部署。

**`fn` 原地晋级，逐字保留。** 其 host_vars 与环境变量原封不动地移入 `prod` 组，因此渲染出的 `docker-compose.yml` 与 `config.toml` 与 `fn` 当前运行的版本逐字节等价；这次重命名既不需要、也没有执行任何重新部署。

**Vault 标签维持 `progress-test` / `progress-prod`。** 占位 prod vault 与线上 test vault 经哈希比对（全程不暴露明文）确认九个 secret 完全一致，因此 `prod` 组沿用 progress-prod 加密的文件，`staging` 继承 progress-test 加密的文件——零重加密、零 keyring 变更。`progress-test` 即 staging 的 vault-id，标签是历史遗留。

**playbook 默认 `target=staging`，未填配置时快速失败。** 前置任务会在任一主机的 `home`、`host_port`、`health_url` 为空或等于 `__FILL_ME__` 哨兵值时拒绝部署（staging 以占位符形态交付，由运维填写）；`cron` 允许为空，表示调度器闲置、手动触发运行——这是验收阶段的正确默认。

## Alternatives considered

**把 `fn` 迁移到一台全新生产主机，`fn` 继续做 dogfooding。** 落选：迁移一个稳定且携带数据的部署是纯粹的风险、没有任何产品收益；`fn` 除了名字之外早已承担生产角色。

**保留原组名，新增第三个 `staging` 组。** 落选："test" 组里跑着生产服务，恰恰是本次要移除的陷阱——名字必须反映事实，否则下一个读者会部署到错误的层级。

**重加密 vault 并把 avpm vault-id 改名为 `progress-staging`。** 落选：收益只是标签美观；为此要动 keyring 并重写线上 secret 文件，而两套密文解出的明文完全一致，功能上零收益。

## Consequences

`ansible-playbook devops/ansible/main.yml` 默认部署到 `oect`；`fn` 仅在 staging 验收后通过显式 `-e target=prod` 更新——这道闸门是流程性的，不是技术性的。两个层级都拉取滚动 `:main` 标签，因此构建必须保持多平台发布（`oect` 是 arm64，`fn` 拉 amd64 变体；用 `docker/build.py --push --all-platforms`）；为下一轮 staging 验证推送更新的 `:main` 不会影响正在运行的 `fn` 容器，直到再次显式部署 prod。staging 携带 `__FILL_ME__` 占位符（`group_vars/staging/env.yml` 的 `host_port`、`health_url`；`host_vars/oect.yml` 的 `home`），首次部署前必须填写。playbook 会把 data 目录交给容器用户（uid/gid 100:101），`init_db` 在数据库无法打开时以 `DBUnavailableException` 响亮失败：tortoise 的 sqlite `ConnectionWrapper` 在 `__aenter__` 内打开失败会泄漏连接锁，而迁移层"降级不崩溃"的默认吞错会让启动死锁而非失败——这是 oect 首次部署时发现的。各环境 vault 的单变量块由 `scripts/vault.py` 管理（`set`/`get`/`list`/`check`/`remove`），其内置 env→vault-id 映射并在解密前清空 `ANSIBLE_VAULT_IDENTITY_LIST`——`check` 只以各环境自身的身份验证全部变量，错放的 secret 会响亮失败，而不是借身份列表回退蒙混解密。`docs/deployment.md`、`docs/observability-deploy.md`、`AGENTS.md` 与 shipping skill 均已写明新的默认目标。
