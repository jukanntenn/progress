"""配置文件加载和验证"""

import toml
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MarkpostConfig:
    """Markpost 配置"""
    base_url: str
    post_key: str


@dataclass
class FeishuConfig:
    """飞书配置"""
    webhook_url: str


@dataclass
class GitHubConfig:
    """GitHub 配置"""
    gh_token: Optional[str] = None


@dataclass
class ScheduleConfig:
    """调度配置"""
    enabled: bool = False
    crontab: str = ""  # crontab 格式，如 "0 */6 * * *"
    verify_mode: bool = False  # 验证模式，每次运行都对比最新和次新提交


@dataclass
class Config:
    """应用配置"""
    database_path: str
    markpost: MarkpostConfig
    feishu: FeishuConfig
    github: GitHubConfig
    schedule: ScheduleConfig
    repos: List[dict]

    @classmethod
    def load_from_file(cls, config_path: str) -> "Config":
        """从 TOML 文件加载配置"""
        config_file = Path(config_path)

        if not config_file.exists():
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        logger.info(f"加载配置文件: {config_path}")

        try:
            data = toml.load(config_file)
        except Exception as e:
            raise ValueError(f"配置文件解析失败: {e}")

        # 解析通用配置
        general = data.get('general', {})
        database_path = general.get('database_path', './progress.db')

        # 解析 Markpost 配置
        markpost_data = data.get('markpost', {})
        if not markpost_data.get('base_url') or not markpost_data.get('post_key'):
            raise ValueError("markpost 配置缺少 base_url 或 post_key")

        markpost = MarkpostConfig(
            base_url=markpost_data['base_url'],
            post_key=markpost_data['post_key']
        )

        # 解析飞书配置
        feishu_data = data.get('feishu', {})
        if not feishu_data.get('webhook_url'):
            raise ValueError("feishu 配置缺少 webhook_url")

        feishu = FeishuConfig(webhook_url=feishu_data['webhook_url'])

        # 解析 GitHub 配置
        github_data = data.get('github', {})
        github = GitHubConfig(gh_token=github_data.get('gh_token'))

        # 解析调度配置
        schedule_data = data.get('schedule', {})
        schedule = ScheduleConfig(
            enabled=schedule_data.get('enabled', False),
            crontab=schedule_data.get('crontab', ''),
            verify_mode=schedule_data.get('verify_mode', False)
        )

        # 解析仓库配置
        repos_data = data.get('repos', {})
        repos_list = repos_data.get('list', [])

        if not repos_list:
            logger.warning("未配置任何仓库")

        # 规范化仓库配置
        repos = []
        for repo in repos_list:
            if not repo.get('name') or not repo.get('url'):
                logger.warning(f"跳过无效的仓库配置: {repo}")
                continue

            # 自动推断分支
            if 'branch' not in repo:
                repo['branch'] = 'main'  # 默认使用 main

            repos.append(repo)

        logger.info(f"加载了 {len(repos)} 个仓库配置")

        return cls(
            database_path=database_path,
            markpost=markpost,
            feishu=feishu,
            github=github,
            schedule=schedule,
            repos=repos
        )
