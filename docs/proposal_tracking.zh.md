# 提案跟踪

[English](proposal_tracking.md) | 中文

Progress 可以跟踪 EIP、Rust RFC、PEP、Django DEP 这类提案仓库。它解析提案元数据，从 git 历史中检测生命周期事件，把事件存入数据库，并为高优先级事件发送通知。

## 事件类型

- `created`：新增了一个提案文件。
- `status_changed`：提案状态发生了变化，但不匹配更具体的类别。
- `accepted`：状态表明已被接受/定稿。
- `rejected`：状态表明被拒绝。
- `withdrawn`：状态表明被撤回/废弃，或某个草案提案文件被删除。
- `postponed`：状态表明被推迟。
- `content_modified`：提案文件发生了变化但未检测到状态变化。
- `resurrected`：状态表明被复活。
- `superseded`：状态表明被取代。

默认触发通知的高优先级事件：

- `created`、`accepted`、`rejected`、`withdrawn`

## 故障排查

### 解析错误

- 症状：日志显示某个提案文件解析失败。
- 修复：确认文件符合该跟踪器类型预期的格式，且 `file_pattern` 只过滤出有效文件。

### 克隆/更新失败

- 症状：日志显示 git clone/reset 失败。
- 修复：确认网络可访问、`repo_url` 可达；检查 `branch` 存在。

### AI（人工智能）分析不可用

- 症状：事件记录存在，但缺少分析摘要/详情。
- 修复：提案跟踪器使用共享的 Pydantic AI agent（智能体）（`progress.cli.ai`，经 `analysis` section 配置：`provider`、`model`、`api_key`、`base_url`）。`analysis.model` 为空时跳过 agent，事件不带摘要直接入库；设置一个模型并重新运行即可。分析失败记为 WARNING 日志，不会中止运行。
