"""数据库初始化和操作"""

import logging
from datetime import datetime
from peewee import SqliteDatabase
from .models import database_proxy, Repository, Report

logger = logging.getLogger(__name__)

# 全局数据库实例
database = None


def init_db(db_path: str):
    """初始化数据库连接"""
    global database
    database = SqliteDatabase(db_path)
    database.connect()
    # 绑定数据库到模型的 proxy
    database_proxy.initialize(database)
    logger.info(f"数据库已连接: {db_path}")


def create_tables():
    """创建数据库表"""
    database.create_tables([Repository, Report], safe=True)
    logger.info("数据库表已创建")


def close_db():
    """关闭数据库连接"""
    global database
    if database:
        database.close()
        logger.info("数据库连接已关闭")


def sync_repositories(repos_config: list) -> None:
    """同步仓库配置到数据库"""
    for repo_config in repos_config:
        repo, created = Repository.get_or_create(
            url=repo_config['url'],
            defaults={
                'name': repo_config['name'],
                'branch': repo_config.get('branch', 'main'),
                'enabled': repo_config.get('enabled', True)
            }
        )

        # 更新现有仓库的配置
        if not created:
            repo.name = repo_config['name']
            repo.branch = repo_config.get('branch', 'main')
            repo.enabled = repo_config.get('enabled', True)
            repo.save()

        if created:
            logger.info(f"新增仓库: {repo.name} ({repo.url})")
        else:
            logger.debug(f"更新仓库配置: {repo.name} ({repo.url})")


def get_enabled_repositories():
    """获取所有启用的仓库"""
    return Repository.select().where(Repository.enabled == True)


def update_repository_commit(repo_id: int, commit_hash: str):
    """更新仓库的最后提交哈希"""
    repo = Repository.get_by_id(repo_id)
    repo.last_commit_hash = commit_hash
    repo.last_check_time = datetime.now()
    repo.save()


def save_report(
    repo_id: int,
    commit_hash: str,
    previous_commit_hash: str,
    commit_count: int,
    markpost_id: str = None,
    markpost_url: str = None,
    report_content: str = None
) -> int:
    """保存报告"""
    report = Report.create(
        repo=repo_id,
        commit_hash=commit_hash,
        previous_commit_hash=previous_commit_hash,
        commit_count=commit_count,
        markpost_id=markpost_id,
        markpost_url=markpost_url,
        report_content=report_content
    )
    logger.info(f"报告已保存: {report.id}")
    return report.id
