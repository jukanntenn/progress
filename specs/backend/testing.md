CLI 端测试框架选型

插件 用途
pytest 核心测试框架
pytest-mock 统一的 Mock 接口，替代unittest.mock
pytest-console-scripts 直接测试 CLI 命令入口
pytest-regressions 黄金测试 (Golden Testing)，验证报告输出
pytest-xdist 并行执行测试，大幅缩短时间
freezegun 冻结时间，测试定时任务和日期相关逻辑
pytest-asyncio 测试异步代码（FastAPI 端点）
pytest-cov 测试覆盖率统计
pytest-httpserver 轻量级 HTTP Mock 服务器

目录结构

```
e2e/
    cli/
    web/
```

web 端测试

dagger + playwright + TypeScript

外部依赖，按照 "可模拟性"和"业务重要性" 分为三个等级，采用不同的测试策略

第一级：完全模拟（单元测试层）
适用依赖：Claude Code CLI、飞书通知、Markpost 服务
核心原则：永远不要在单元测试中调用真实外部服务

```python
def test_xxx(mocker):
    mock_run = mocker.patch("subprocess.run")
    mock_post = mocker.patch("requests.post")
```

第二级：轻量级 Fake 服务（集成测试层）
适用依赖：GitHub API、Git 命令
核心原则：使用真实协议的轻量级实现，而非 Mock，提高测试真实性

不要 Mock Git 命令！这是社区的反模式。Git 命令的行为非常复杂，Mock 无法覆盖所有边缘情况。正确做法是：

```python
# tests/integration/test_git_client.py
import tempfile
import git

def test_git_client_clone_and_pull():
    # 1. 创建一个临时本地Git仓库作为测试源
    with tempfile.TemporaryDirectory() as tmpdir:
        # 初始化源仓库
        repo = git.Repo.init(tmpdir)
        with open(f"{tmpdir}/README.md", "w") as f:
            f.write("# Test Repo")
        repo.index.add(["README.md"])
        commit = repo.index.commit("Initial commit")

        # 2. 使用真实GitClient克隆仓库
        client = GitClient(data_dir="./test-data")
        cloned_repo = client.clone(f"file://{tmpdir}", branch="main")

        # 3. 验证克隆结果
        assert cloned_repo.working_dir.endswith("test-repo")
        assert cloned_repo.head.commit.hexsha == commit.hexsha

        # 4. 测试Pull操作
        with open(f"{tmpdir}/new_file.txt", "w") as f:
            f.write("New content")
        repo.index.add(["new_file.txt"])
        new_commit = repo.index.commit("Add new file")

        client.pull(cloned_repo)
        assert cloned_repo.head.commit.hexsha == new_commit.hexsha
```

对于报告生成这类输出复杂的功能，使用pytest-regressions进行黄金测试
