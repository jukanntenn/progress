"""GitHub CLI 交互"""

import os
import shutil
import subprocess
import logging
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


class GitHubClient:
    """使用 GitHub CLI 与 GitHub 交互"""

    def __init__(self, workspace_dir: str = "/tmp/progress_tracker", gh_token: Optional[str] = None):
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.gh_token = gh_token
        logger.debug(f"工作目录: {self.workspace_dir}")

        # 配置 Git 以更好地处理网络问题
        self._configure_git()

    def _configure_git(self):
        """配置 Git 以更好地处理网络问题"""
        try:
            # 增加重试次数和超时时间
            configs = [
                ("http.lowSpeedLimit", "0"),  # 禁用低速限制
                ("http.lowSpeedTime", "99999"),  # 长时间超时
                ("http.postBuffer", "524288000"),  # 500MB buffer
            ]
            for key, value in configs:
                self._run_command([
                    "git", "config", "--global", key, value
                ])
                logger.debug(f"Git 配置: {key} = {value}")
        except Exception as e:
            logger.warning(f"配置 Git 失败（非致命）: {e}")

    def clone_or_update(self, repo_url: str, branch: str) -> Path:
        """克隆或更新仓库（统一使用 GitHub CLI）

        Args:
            repo_url: 仓库 URL (owner/repo 格式)
            branch: 分支名称

        Returns:
            仓库路径
        """
        repo_path = self.workspace_dir / repo_url.replace("/", "_")

        if not repo_path.exists():
            # 首次克隆：使用 gh repo clone，只获取最近 2 个 commit（快速）
            logger.info(f"克隆仓库: {repo_url} (branch: {branch})")
            self._run_command_with_retry([
                "gh", "repo", "clone", repo_url, str(repo_path),
                "--", "--branch", branch, "--single-branch", "--depth", "2"
            ])
        else:
            # 后续更新：使用 gh repo sync 同步仓库
            logger.info(f"同步仓库: {repo_url} (branch: {branch})")

            # 如果是浅克隆，先转换为完整克隆
            if (repo_path / ".git" / "shallow").exists():
                logger.debug("检测到浅克隆，转换为完整克隆...")
                self._run_command([
                    "git", "-C", str(repo_path), "fetch", "--unshallow"
                ])

            # 使用 gh repo sync 同步仓库（需要在仓库目录内执行）
            # gh repo sync 会自动同步当前仓库与远程 origin
            self._run_command_with_retry([
                "gh", "repo", "sync",
                "--branch", branch
            ], cwd=str(repo_path))

        return repo_path

    def get_current_commit(self, repo_path: Path) -> str:
        """获取当前 commit hash"""
        result = self._run_command(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"]
        )
        return result.strip()

    def get_previous_commit(self, repo_path: Path) -> Optional[str]:
        """获取次新 commit hash（HEAD^1）

        Returns:
            次新 commit hash，如果不存在则返回 None
        """
        try:
            result = self._run_command(
                ["git", "-C", str(repo_path), "rev-parse", "HEAD^1"]
            )
            return result.strip() if result.strip() else None
        except RuntimeError:
            # 可能是首次提交，没有父 commit
            return None

    def get_commit_diff(self, repo_path: Path,
                       old_commit: Optional[str],
                       new_commit: str) -> str:
        """获取两个 commit 之间的 diff

        Args:
            repo_path: 仓库路径
            old_commit: 旧的 commit hash (None 表示获取最新两个 commit 的 diff)
            new_commit: 新的 commit hash

        Returns:
            diff 内容
        """
        if old_commit:
            result = self._run_command([
                "git", "-C", str(repo_path), "diff",
                f"{old_commit}..{new_commit}"
            ])
        else:
            # 首次运行，对比 HEAD 和 HEAD^1
            result = self._run_command([
                "git", "-C", str(repo_path), "diff",
                "HEAD^1..HEAD"
            ])

        return result

    def get_commit_messages(self, repo_path: Path,
                           old_commit: Optional[str],
                           new_commit: str) -> List[str]:
        """获取 commit 消息列表"""
        if old_commit:
            result = self._run_command([
                "git", "-C", str(repo_path), "log",
                f"{old_commit}..{new_commit}",
                "--pretty=format:%s"
            ])
        else:
            # 首次运行，获取最新 commit 的消息
            result = self._run_command([
                "git", "-C", str(repo_path), "log",
                "--pretty=format:%s", "-1"
            ])

        return result.strip().split("\n") if result.strip() else []

    def get_commit_count(self, repo_path: Path,
                        old_commit: Optional[str],
                        new_commit: str) -> int:
        """获取 commit 数量"""
        if not old_commit:
            return 1

        result = self._run_command([
            "git", "-C", str(repo_path), "rev-list",
            "--count", f"{old_commit}..{new_commit}"
        ])
        return int(result.strip())

    def _run_command_with_retry(self, cmd: List[str], max_retries: int = 3, retry_delay: int = 5, cwd: Optional[str] = None) -> str:
        """执行命令，失败时重试

        Args:
            cmd: 命令列表
            max_retries: 最大重试次数
            retry_delay: 重试延迟（秒）
            cwd: 工作目录

        Returns:
            命令输出
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                return self._run_command(cmd, cwd=cwd)
            except RuntimeError as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(f"命令执行失败（第 {attempt + 1}/{max_retries} 次尝试），{retry_delay} 秒后重试...")
                    time.sleep(retry_delay)
                else:
                    logger.error(f"命令执行失败，已达最大重试次数 {max_retries}")
                    raise last_error

    def _run_command(self, cmd: List[str], cwd: Optional[str] = None) -> str:
        """执行命令并返回输出"""
        try:
            logger.debug(f"执行命令: {' '.join(cmd)}" + (f" (cwd: {cwd})" if cwd else ""))

            # 如果是 gh 命令且配置了 token，则设置环境变量
            env = None
            if cmd[0] == "gh" and self.gh_token:
                env = os.environ.copy()
                env["GH_TOKEN"] = self.gh_token
                logger.debug("使用配置的 GH_TOKEN")

            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                env=env,
                cwd=cwd
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"命令执行失败: {e.stderr}")
            raise RuntimeError(f"命令执行失败: {e.stderr}") from e
        except subprocess.TimeoutExpired:
            logger.error("命令执行超时")
            raise RuntimeError("命令执行超时") from None
