# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Progress Tracker 是一个 GitHub 代码变更跟踪工具，通过监控开源项目的代码变化，调用 Claude Code CLI 进行智能分析，生成 Markdown 报告并上传到 Markpost 平台。

## 核心架构

项目采用模块化设计，主要组件包括：

- **cli.py** - 主流程协调，串联所有组件
- **config.py** - 配置文件解析（TOML 格式）
- **models.py** - Peewee ORM 数据模型定义
- **db.py** - 数据库操作（使用 DatabaseProxy 延迟绑定）
- **github.py** - 通过 GitHub CLI 与 GitHub 交互（gh repo clone/sync）
- **analyzer.py** - 调用 Claude Code CLI 分析代码 diff
- **reporter.py** - 生成 Markdown 格式的变更报告
- **notifier.py** - 发送飞书 webhook 通知

### 关键设计

1. **GitHub 交互**：统一使用 GitHub CLI（gh）而非直接 git 命令，首次克隆使用浅克隆（depth=2），更新时使用 gh repo sync
2. **数据库**：使用 Peewee ORM + SQLite，通过 DatabaseProxy 实现延迟绑定，便于测试
3. **Claude 分析**：通过管道将 diff 传递给 claude CLI，期望返回 JSON 格式的结构化分析结果
4. **验证模式**：verify_mode=true 时强制对比最新和次新提交，用于测试；生产环境应为 false

## 开发命令

### 依赖管理

```bash
# 安装依赖
uv sync

# 安装项目为可编辑包
uv pip install -e .
```

### 运行

```bash
# 手动运行所有仓库检查
progress -c config.toml

# 检查特定仓库
progress -c config.toml -r vite

# 详细输出
progress -c config.toml -v
```

### 测试

```bash
# 运行测试
uv run pytest
```

### 代码质量

```bash
# 代码格式化
uv run black src/

# 代码检查
uv run ruff check src/
```

### Docker 构建

```bash
# 单架构构建（当前平台）
docker build -t progress:latest .

# 多架构构建
chmod +x build-docker.sh
export REGISTRY="docker.io/your-username"
./build-docker.sh

# 使用 Docker Compose
docker-compose up -d
docker-compose logs -f
```

## 配置文件结构

config.toml 是项目的核心配置文件，包含以下部分：

- **[general]** - 数据库路径
- **[markpost]** - 报告上传 API 配置
- **[feishu]** - 飞书通知 webhook
- **[github]** - GitHub token（可选）
- **[schedule]** - 调度模式配置
  - enabled: 是否启用调度
  - crontab: crontab 格式的时间配置
  - verify_mode: 验证模式（测试用）
- **[[repos.list]]** - 监控的仓库列表
  - name: 仓库名称
  - url: GitHub 仓库（owner/repo 格式）
  - branch: 分支（默认 main）
  - enabled: 是否启用（默认 true）

## 工作流程

1. 加载 config.toml 配置
2. 初始化 SQLite 数据库
3. 将配置的仓库同步到数据库（db.sync_repositories）
4. 对每个启用的仓库：
   - 使用 GitHub CLI 克隆/更新仓库（GitHubClient.clone_or_update）
   - 对比当前 commit 与上次记录的 commit hash
   - 如有变更，获取 diff 和 commit messages
   - 调用 Claude Code CLI 分析 diff（ClaudeCodeAnalyzer.analyze_diff）
   - 生成 Markdown 报告（MarkdownReporter）
   - 更新数据库状态（验证模式下不更新）
5. 汇总所有仓库的报告
6. 上传到 Markpost
7. 发送飞书通知

## 重要注意事项

1. **Claude Code 集成**：analyzer.py 通过管道调用 claude CLI，期望返回包含 summary、added_structures、removed_structures、modified_functions、added_functions、removed_functions、api_changes、important_changes 字段的 JSON 结果。解析逻辑需要处理多种可能的返回格式（直接 JSON、代码块等）

2. **GitHub CLI 认证**：优先使用 config.toml 中的 gh_token，其次使用已登录的 GitHub session（~/.config/gh）

3. **错误处理**：单个仓库失败不影响其他仓库继续检查。所有外部调用都设置了超时（GitHub: 5 分钟，Claude: 10 分钟）

4. **数据持久化**：数据库文件默认保存在 ./data/progress.db，Docker 部署时需要挂载 /app/data 目录

5. **调度模式**：启用后容器会持续运行并按 crontab 配置自动执行，首次启动会立即执行一次检查验证配置

## 项目依赖

- Python 3.12+
- uv - Python 包管理工具
- GitHub CLI (gh) - GitHub 命令行工具
- Claude Code (claude) - Claude 命令行工具
- Peewee 3.18.3 - ORM
- Click 8.3.1 - CLI 框架
- Requests 2.32.5 - HTTP 客户端

不要瞎编命令，不清楚的地方要求用户主动提供使用文档
不允许代码内 import，所有 import 放在文件头
