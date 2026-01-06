"""CLI 主流程"""

import logging
import click
import requests
from datetime import datetime

from .config import Config
from .db import (
    init_db, create_tables, close_db, sync_repositories,
    get_enabled_repositories, update_repository_commit, save_report
)
from .github import GitHubClient
from .analyzer import ClaudeCodeAnalyzer
from .reporter import MarkdownReporter
from .notifier import FeishuNotifier

logger = logging.getLogger(__name__)


@click.command()
@click.option('--config', '-c', default='config.toml', help='配置文件路径')
@click.option('--verbose', '-v', is_flag=True, help='详细输出')
@click.option('--repo', '-r', help='只检查指定仓库')
def main(config: str, verbose: bool, repo: str):
    """Progress Tracker - GitHub 代码变化跟踪工具"""

    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    try:
        # 1. 加载配置
        logger.info(f"加载配置文件: {config}")
        cfg = Config.load_from_file(config)

        # 2. 初始化数据库
        init_db(cfg.database_path)
        create_tables()

        # 3. 同步仓库配置到数据库
        sync_repositories(cfg.repos)

        # 4. 获取需要检查的仓库
        repos = list(get_enabled_repositories())
        if repo:
            repos = [r for r in repos if r.name == repo]

        logger.info(f"开始检查 {len(repos)} 个仓库")

        # 5. 初始化组件
        github_client = GitHubClient(gh_token=cfg.github.gh_token)
        analyzer = ClaudeCodeAnalyzer()
        reporter = MarkdownReporter()
        notifier = FeishuNotifier(cfg.feishu.webhook_url)

        # 6. 遍历检查每个仓库，收集分析结果
        repo_reports = []
        total_commits = 0

        for repo_obj in repos:
            try:
                result = _check_repository(
                    repo_obj, github_client, analyzer,
                    reporter, cfg
                )
                if result:
                    repo_reports.append(result)
                    total_commits += result['commit_count']
            except Exception as e:
                logger.error(f"检查仓库 {repo_obj.name} 失败: {e}", exc_info=True)
                continue

        # 7. 生成汇总报告
        if repo_reports:
            logger.info(f"共检查了 {len(repo_reports)} 个仓库，{total_commits} 个提交")
            aggregated_report = reporter.generate_aggregated_report(repo_reports)

            # 8. 上传到 Markpost
            logger.info("上传汇总报告到 Markpost...")
            title = f"开源项目代码变更汇总 - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            markpost_url = _upload_to_markpost(aggregated_report, title, cfg.markpost)
            logger.info(f"报告已上传: {markpost_url}")

            # 9. 发送飞书通知
            logger.info("发送飞书通知...")
            summary = f"本次检查了 {len(repo_reports)} 个项目，共 {total_commits} 个提交"
            notifier.send_notification(
                "GitHub 项目监控",
                total_commits,
                summary,
                markpost_url
            )
        else:
            logger.info("没有仓库有新变更，跳过报告生成")

        logger.info("所有仓库检查完成")

    except Exception as e:
        logger.error(f"程序执行失败: {e}", exc_info=True)
        raise click.ClickException(str(e))
    finally:
        # 10. 关闭数据库连接
        close_db()


def _check_repository(
    repo,
    github_client: GitHubClient,
    analyzer: ClaudeCodeAnalyzer,
    reporter: MarkdownReporter,
    cfg: Config
):
    """检查单个仓库的更新，返回报告数据"""
    logger = logging.getLogger(f"progress_tracker.{repo.name}")

    logger.info(f"检查仓库: {repo.url} (branch: {repo.branch})")

    # 1. 克隆/更新仓库
    repo_path = github_client.clone_or_update(repo.url, repo.branch)

    # 2. 获取当前 commit
    current_commit = github_client.get_current_commit(repo_path)
    logger.info(f"当前 commit: {current_commit[:8]}")

    # 验证模式：总是对比最新和次新提交
    if cfg.schedule.verify_mode:
        logger.info("验证模式：对比最新和次新提交")
        previous_commit = github_client.get_previous_commit(repo_path)
        if not previous_commit:
            logger.warning("仓库只有一个 commit，无法对比，跳过")
            return None
        logger.info(f"次新 commit: {previous_commit[:8]}")
    else:
        # 3. 检查是否有新提交
        if repo.last_commit_hash == current_commit:
            logger.info("没有新提交，跳过")
            return None

        # 4. 获取 diff 和提交信息
        previous_commit = repo.last_commit_hash

        # 首次运行：获取次新 commit 作为对比基准
        if not previous_commit:
            logger.info("首次检查，对比最新和次新 commit")
            previous_commit = github_client.get_previous_commit(repo_path)
            if not previous_commit:
                logger.warning("仓库只有一个 commit，无法对比，跳过")
                # 保存当前 commit，下次再检查
                update_repository_commit(repo.id, current_commit)
                return None
            logger.info(f"次新 commit: {previous_commit[:8]}")

    commit_messages = github_client.get_commit_messages(
        repo_path, previous_commit, current_commit
    )
    commit_count = github_client.get_commit_count(
        repo_path, previous_commit, current_commit
    )

    logger.info(f"发现 {commit_count} 个新提交")

    # 获取 diff
    diff = github_client.get_commit_diff(repo_path, previous_commit, current_commit)

    if not diff.strip():
        logger.warning("Diff 为空，跳过分析")
        update_repository_commit(repo.id, current_commit)
        return None

    # 5. 调用 Claude Code 分析
    logger.info("正在分析代码变化...")
    analysis = analyzer.analyze_diff(
        repo.name, repo.branch, diff, commit_messages
    )

    # 6. 生成单个仓库的报告（用于汇总）
    repo_content = reporter.generate_repository_report(
        repo.name, repo.url, repo.branch,
        current_commit, previous_commit or '', commit_count,
        analysis, commit_messages
    )

    # 7. 更新数据库状态（验证模式下不更新）
    if not cfg.schedule.verify_mode:
        update_repository_commit(repo.id, current_commit)
    else:
        logger.info("验证模式：不更新数据库状态")

    # 8. 返回报告数据
    logger.info(f"仓库 {repo.name} 检查完成")

    return {
        'repo_name': repo.name,
        'content': repo_content,
        'commit_count': commit_count,
        'analysis': analysis
    }


def _upload_to_markpost(content: str, title: str, markpost_config) -> str:
    """上传内容到 Markpost"""
    url = f"{markpost_config.base_url.rstrip('/')}/{markpost_config.post_key}"
    payload = {
        "title": title,
        "body": content
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        post_id = result.get("id")

        # 构造文章 URL (格式: https://markpost.bytehome.fun/{post_id})
        return f"{markpost_config.base_url.rstrip('/')}/{post_id}"
    except requests.RequestException as e:
        logger.error(f"上传到 Markpost 失败: {e}")
        raise RuntimeError(f"上传到 Markpost 失败: {e}") from e


if __name__ == '__main__':
    main()
