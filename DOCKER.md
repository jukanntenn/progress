# Docker 部署指南

本文档介绍如何使用 Docker 部署 Progress Tracker。

## 镜像信息

- **镜像名称**: progress
- **支持架构**: linux/amd64, linux/arm64
- **基础镜像**: python:3.13-slim
- **包含组件**:
  - Python 3.13
  - Git
  - GitHub CLI (gh)
  - Progress Tracker 应用

## 快速开始

### 1. 准备配置文件

复制配置文件示例并根据需要修改：

```bash
cp config.toml.example config.toml
# 编辑 config.toml，填入必要的配置
```

创建数据目录：

```bash
mkdir -p data
```

### 2. 使用 Docker Compose (推荐)

```bash
# 启动容器
docker-compose up -d

# 查看日志
docker-compose logs -f

# 手动运行一次
docker-compose run --rm progress
```

### 3. 使用 Docker 命令

```bash
# 直接运行
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest

# 后台运行
docker run -d \
  --name progress \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

## 构建镜像

### 方式一: 单架构构建 (当前平台)

```bash
# 本地构建
docker build -t progress:latest .

# 运行
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

### 方式二: 单架构构建并加载到本地 Docker

```bash
# 构建当前架构的镜像并加载到本地 Docker
docker buildx build \
  --platform linux/amd64 \
  -t progress:latest \
  --load \
  .
```

### 方式三: 多架构构建并推送到 Registry (推荐)

使用提供的构建脚本构建支持 AMD64 和 ARM64 的镜像：

```bash
# 给脚本执行权限
chmod +x build-docker.sh

# 构建并推送到 Docker Hub
# 需要先设置 REGISTRY 环境变量
export REGISTRY="docker.io/your-username"
./build-docker.sh
```

**手动多架构构建**:

```bash
# 创建 builder
docker buildx create --name multiarch --use

# 构建并加载到本地 Docker (只支持当前架构)
docker buildx build \
  --platform linux/amd64 \
  -t progress:latest \
  --load \
  .

# 构建并推送到 registry
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t your-registry/progress:latest \
  --push \
  .
```

## 配置

### 通过配置文件

主要配置通过挂载的 `config.toml` 文件提供：

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  progress:latest
```

### 通过环境变量

可以在配置文件中设置 `gh_token`，或通过环境变量传递（如果程序支持）：

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -e GH_TOKEN=your_token_here \
  progress:latest
```

### GitHub CLI 认证

容器内已安装 GitHub CLI，支持两种认证方式：

1. **配置文件中设置 token** (推荐):

在 `config.toml` 中添加：
```toml
[github]
gh_token = "ghp_xxxxxxxxxxxxxxxxxxxx"
```

2. **使用已登录的 GitHub session**:

挂载 GitHub 配置目录：
```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v ~/.config/gh:/root/.config/gh:ro \
  progress:latest
```

## 运行模式

### 单次运行（默认）

容器默认执行一次检查后退出：

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

### 调度模式（推荐）

在配置文件中启用调度后，容器会持续运行并按配置的时间间隔自动执行检查。

**配置调度**：

在 `config.toml` 中添加：

```toml
[schedule]
# 启用调度模式
enabled = true
# 每 6 小时执行一次
crontab = "0 */6 * * *"
# 验证模式：每次运行都对比最新和次新提交（用于测试）
verify_mode = false
```

**运行调度容器**：

```bash
docker run -d \
  --name progress \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

容器启动后会：
1. 立即执行一次检查（验证配置是否正确）
2. 启动 cron 守护进程
3. 按 crontab 配置自动执行后续检查

**Crontab 格式**：

```
┌───────────── 分钟 (0 - 59)
│ ┌───────────── 小时 (0 - 23)
│ │ ┌───────────── 日 (1 - 31)
│ │ │ ┌───────────── 月 (1 - 12)
│ │ │ │ ┌───────────── 周 (0 - 7) (周日为 0 或 7)
│ │ │ │ │
* * * * *
```

常用示例：
- `"0 */6 * * *"` - 每 6 小时执行一次
- `"0 0 * * *"` - 每天凌晨 0 点执行
- `"0 */2 * * *"` - 每 2 小时执行一次
- `"*/30 * * * *"` - 每 30 分钟执行一次
- `"0 9,18 * * *"` - 每天早上 9 点和晚上 6 点执行

**验证模式**：

用于测试调度功能是否正常工作。开启后每次运行都会生成报告（对比最新和次新提交），不会因数据库中已记录最新提交而跳过。

```toml
[schedule]
enabled = true
crontab = "*/5 * * * *"  # 每 5 分钟执行一次（测试用）
verify_mode = true  # 启用验证模式
```

生产环境使用时应将 `verify_mode` 设置为 `false`。

### 一次性执行（调度禁用时）

```bash
docker run --rm \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

## 存储卷

容器使用以下卷：

- `/app/config.toml` - 配置文件 (只读)
- `/app/data` - 数据目录 (读写)
  - 数据库文件：`progress.db` (默认)
  - 建议在宿主机创建 `data` 目录并挂载到此处，确保数据持久化

**重要**：数据库文件默认保存在 `/app/data/progress.db`，请确保挂载 `/app/data` 目录以实现数据持久化。

## 故障排查

### 查看日志

```bash
# Docker Compose
docker-compose logs -f

# Docker
docker logs -f progress
```

### 进入容器调试

```bash
docker exec -it progress bash

# 在容器内手动运行
progress --config /app/config.toml --verbose

# 测试 GitHub CLI
gh auth status
gh repo list
```

### 常见问题

1. **GitHub CLI 认证失败**
   - 在 `config.toml` 中配置 `gh_token`
   - 或挂载已登录的 `~/.config/gh` 目录

2. **数据库文件权限**
   - 确保 `data` 目录有正确的读写权限
   - `chmod 777 data` (开发环境)

3. **网络问题**
   - 确保容器可以访问 GitHub API
   - 检查代理设置

4. **架构不匹配**
   - 使用 `--platform` 指定架构
   - `docker run --platform linux/amd64 ...`

## 资源限制

可以限制容器资源使用：

```bash
docker run --rm \
  --memory="512m" \
  --cpus="1.0" \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  progress:latest
```

## 生产部署建议

1. **使用特定的镜像标签**
   - 不要使用 `latest`，使用版本号如 `v1.0.0`

2. **配置健康检查**
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
     CMD progress --version || exit 1
   ```

3. **使用私有 registry**
   - 将镜像推送到私有 Docker Registry
   - 或使用 GitHub Container Registry, GitLab Registry 等

4. **监控和日志**
   - 集成日志收集系统
   - 配置监控告警

5. **安全加固**
   - 使用非 root 用户运行
   - 限制网络访问
   - 定期更新基础镜像

## 镜像仓库

如果要发布到公共或私有镜像仓库：

### Docker Hub
```bash
docker tag progress:latest username/progress:latest
docker push username/progress:latest
```

### GitHub Container Registry
```bash
docker tag progress:latest ghcr.io/username/progress:latest
docker push ghcr.io/username/progress:latest
```

### 阿里云容器镜像服务
```bash
docker tag progress:latest registry.cn-hangzhou.aliyuncs.com/username/progress:latest
docker push registry.cn-hangzhou.aliyuncs.com/username/progress:latest
```
