# Progress Tracker

GitHub 代码变更跟踪工具 - 自动监控开源项目的代码变化，通过 Claude 智能分析并生成报告。

## 功能特性

- 支持监控多个 GitHub 仓库
- 自动检测代码变更并生成 diff
- 调用 Claude Code CLI 进行智能分析
- 生成 Markdown 格式的变更报告
- 上传报告到 Markpost 平台
- 推送飞书 webhook 通知
- 使用 SQLite 存储历史记录

## 前置要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) - Python 包管理工具
- [GitHub CLI](https://cli.github.com/) - GitHub 命令行工具
- [Claude Code](https://claude.com/claude-code) - Claude 命令行工具
- Markpost 账号（用于托管报告）
- 飞书 webhook（可选，用于接收通知）

## 安装

```bash
# 克隆项目
cd /path/to/progress

# 使用 uv 安装依赖
uv sync

# 安装项目
uv pip install -e .
```

## 配置

1. 复制配置文件示例：

```bash
cp config.toml.example config.toml
```

2. 编辑配置文件：

```bash
vim config.toml
```

配置说明：

```toml
[general]
database_path = "./progress.db"  # SQLite 数据库路径

[markpost]
base_url = "https://markpost.example.com"  # Markpost 地址
post_key = "your-post-key"  # Markpost post key

[feishu]
webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/xxx"  # 飞书 webhook

[[repos.list]]
name = "vite"  # 仓库名称
url = "vitejs/vite"  # GitHub 仓库 (owner/repo)
branch = "main"  # 分支（可选，默认 main）
enabled = true  # 是否启用（可选，默认 true）
```

## 使用

### 手动运行

```bash
# 检查所有仓库
progress -c config.toml

# 检查特定仓库
progress -c config.toml -r vite

# 详细输出
progress -c config.toml -v
```

### 定时任务

使用 crontab 配置定时检查：

```bash
# 编辑 crontab
crontab -e

# 每小时检查一次
0 * * * * cd /home/alice/Workspace/progress && uv run progress -c config.toml >> /var/log/progress_tracker.log 2>&1

# 每 30 分钟检查一次
*/30 * * * * cd /home/alice/Workspace/progress && uv run progress -c config.toml >> /var/log/progress_tracker.log 2>&1
```

## 工作流程

1. **加载配置** - 读取 config.toml 配置文件
2. **同步仓库** - 将配置的仓库同步到数据库
3. **检查更新** - 对每个启用的仓库：
   - 使用 GitHub CLI 拉取最新代码
   - 对比上次 commit hash
   - 如有变更，获取 diff 和 commit messages
   - 调用 Claude Code 分析代码变化
   - 生成 Markdown 报告
   - 上传到 Markpost
   - 发送飞书通知
   - 更新数据库状态
4. **完成** - 输出日志摘要

## 报告示例

生成的 Markdown 报告包含：

- 仓库信息和提交范围
- 变更摘要
- 提交消息列表
- 新增/删除的数据结构
- 新增/修改/删除的函数和方法
- API 变更
- 重要变更说明

## 项目结构

```
progress/
├── pyproject.toml              # 项目配置
├── config.toml                 # 配置文件
├── src/
│   └── progress_tracker/
│       ├── cli.py              # CLI 入口
│       ├── config.py           # 配置加载
│       ├── models.py           # 数据模型
│       ├── db.py               # 数据库操作
│       ├── github.py           # GitHub CLI 交互
│       ├── analyzer.py         # Claude 分析
│       ├── reporter.py         # 报告生成
│       └── notifier.py         # 飞书通知
└── tests/
```

## 错误处理

- 单个仓库失败不影响其他仓库
- 所有外部调用设置超时（GitHub: 5 分钟，Claude: 10 分钟）
- 详细的日志记录

## 开发

```bash
# 运行测试
uv run pytest

# 代码格式化
uv run black src/
uv run ruff check src/
```

## License

MIT
