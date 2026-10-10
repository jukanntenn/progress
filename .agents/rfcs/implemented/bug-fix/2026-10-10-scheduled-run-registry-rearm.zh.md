# RFC: scheduled-run 依据 registry 成员变化重新 arm

Status: implemented

[English](2026-10-10-scheduled-run-registry-rearm.md) | 中文

## Problem

按集成覆盖调度特性（[2026-10-08](../feature/2026-10-08-per-integration-schedule-overrides.zh.md)）把调度分组解析移进了 `scheduled-run` 行的 apply，在 arm 时刻对 `ctx.integrations.names` 做快照。但集成实例是 `integrations` 行的子纤维，而 kernel 分多轮 pass 收敛：第一轮 apply 兄弟行——`integrations` 行提供一个空 registry 并把子纤维挂为 PENDING——第二轮才加载这些子纤维，实例在那时才真正进入 registry。兄弟行 `scheduled-run` 在第一轮 apply，因此它的快照在首次 boot 时结构性地为空。2026-10-08 22:59 部署到 staging 后，arm 出的是 `30 8,22 * * * -> (none)`，此后每次定时 run 都执行零个集成，持续两天（issue [#36](https://github.com/jukanntenn/progress/issues/36)）。覆盖特性之前的代码 arm 的是 `every(cron, runner.run_once)`——成员在触发时解析——挂载顺序从来不是承重墙；而已有测试 boot 的树使用预填充的静态 registry（没有子纤维），两轮 pass 的形态因此从未被测试覆盖。

同一事故还暴露了第二个缺陷：零集成的 run 以 `exit_code=0` 完成，`progress.pipeline.last_success_epoch` 持续刷新，Uptime Kuma 推送报 `status=up`。"pipeline silent" 告警度量的是成功的新鲜度，而空 run 就是一次成功——这类故障在结构上对所有已部署的告警不可见。

## Decision

### Registry 成员是一个事件

`@register` shim 在每次实例 add/remove 之后发出 `integration/registry-changed`（`emit` 模式的 catalog 事件，携带变更后的成员名列表）。成员变化本来就隐式存在于树中——boot 第二轮 pass、L3 插件安装、集成的纤维重启——只是没有东西在观察它们；现在流水线对三者拥有同一个通知点。

### Arm 可重入，而非一次性

`scheduled-run` 行的 apply 把调度分组构建放进 `_rearm()`：先 dispose 当前的调度器条目，从活的 DB section 重新解析 override，对活的 registry 重新分组，再 arm 新条目。它在 apply 时运行一次，并在每个 `integration/registry-changed` 上再次运行，由锁串行化（boot 时每个子纤维各发一次事件；每次 re-arm 读取当前状态，因此无论次数多少最终收敛）。可观测 gauge 读取可变的 arm-state 容器而非 apply 时的闭包，re-arm 无需重注册仪表即可见；`last_success` 跨 re-arm 存留。由纤维 teardown 置位的 closed 标志让树卸载期间的迟到事件成为空操作。arm 的正确性从此不再依赖 settle pass 的顺序。

### 覆盖不变量让故障报警而非静默成功

每次触发都检查每个已挂载的集成属于某个已 arm 的分组。已挂载但未被调度的集成意味着调度与 registry 脱节；此时该次 run 按失败上报——Kuma `status=down`、不刷新 `last_success`、一条 ERROR 日志、一个 `progress.schedule.coverage_drift` 业务事件——尽管 `RunOutcome.exit_code` 本身不变。这有意从活状态计算而非信任已 arm 的分组，因此它本可在原始回归的第一次触发就报警，并在未来的任何脱节（丢失的 re-arm、由坏纤维塑形的调度）发生时于一个 expected-gap 窗口内报警，而不是永不报警。

### boot 窗口宁可响亮失败，不静默通过

第一轮 pass 的 arm 与第二轮 pass 的 re-arm 之间，已 arm 的分组可能为空而集成正在挂载；落在这个窗口里的 cron 触发会撞上覆盖不变量并按失败上报，而不是对空集成功。触发之间相隔数小时而窗口只有毫秒级；不补跑本就是调度器已文档化的语义。

## Testing

`tests/component/test_scheduled_run_arming.py` boot 真实的 shim 树——子纤维、真实的两轮 settle、真实的 scheduler 与 scheduled-run 行——等待 re-arm 完成，直接触发已 arm 的 trigger，断言已挂载的集成确实运行；该测试在修复前的源码上失败。`tests/unit/runtime/test_scheduled_run.py` 新增：事件驱动的 re-arm（触发时运行新挂载的集成）、drift 判定（已挂载但未调度 ⇒ `coverage_drift` 业务事件、Kuma 推送 `success=False`）、以及无 drift 判定（`success=True`）。

## Alternatives considered

**触发时惰性解析成员。** 每次触发的解析能修好全局分组，但修不好条目集合：override 塑形的独立调度器条目仍然缺失（条目由空 registry arm 出来），override 的集成会静默不运行——同一缺陷上移了一层。

**在行的 apply 内部等待子纤维就绪。** kernel 没有暴露兄弟行可等待的"树已收敛"钩子，而一个合法为空的 registry（未配置任何集成）会让任何等待填充的循环挂死 boot。

**在父纤维 load 内同步 apply 子纤维。** 为一个消费者改动 kernel 挂载语义，颠覆了整个组合系统所依赖的 settle 模型；缺陷在消费者的假设里，不在 kernel。

**无条件把零集成 run 判为失败。** 所有集成都 override 离开全局 cron 的部署会合法地 arm 出空的全局分组（特性 RFC 保留的 pre-override idle-cron 行为）；让这些 run 失败会狼来了。覆盖不变量才是精确形式：只在已挂载的集成无处被调度时失败。

## Consequences

- 调度分组的正确性不再依赖挂载时机，且活的 registry 变化——L3 插件安装、集成的纤维重启、recompose——现在无需等待 L0 reload 即可重塑调度。特性 RFC 的 hot-update 一节已同步更新。
- boot 时每个集成的子纤维触发一次 re-arm（串行、DB 轻量、每次毫秒级）；最后一次读取完整状态并胜出，中间形态对任何要紧的触发都不可见。
- drift 判定翻转 Kuma 推送与 `last_success`，但不翻转 `RunOutcome.exit_code`，run 层的失败指标看不到它；基于 `progress.schedule.coverage_drift` 的专用 Grafana 告警与监控 runbook 中所有规则接线一样，推迟到基础设施侧的规则文件。
- `scheduled-run armed: <cron> -> <members>` 日志行现在被一个测试钉住，成为运维排障界面——它正是 #36 排查时第一眼看的地方，因此格式变更必须同步更新组件测试。
