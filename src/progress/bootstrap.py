"""Application bootstrap: DB initialization, config resolution, and component wiring."""

import logging

from .config import Config
from .contrib.repo.reporter import MarkdownReporter
from .contrib.repo.repository import RepositoryManager
from .contrib.proposal import ProposalTracker
from .db import create_tables, init_db, log_db_state, resolve_db_path
from .git import GitClient, GitHubClient
from .ai import create_analyzer
from .utils.markpost import MarkpostClient
from .utils.timezone import get_now

logger = logging.getLogger(__name__)


async def initialize_components(cfg, config_path: str | None = None):
    """Initialize all application components and return runtime objects."""
    db_path = resolve_db_path(cfg.data_dir, config_path)
    await init_db(db_path)
    await create_tables()
    await log_db_state()

    cfg = await resolve_runtime_config(cfg)

    markpost_client = None
    if cfg.markpost.enabled and cfg.markpost.url:
        markpost_client = MarkpostClient(cfg.markpost)

    analyzer = create_analyzer(config=cfg.analysis)
    reporter = MarkdownReporter()
    git_client = GitClient(timeout=cfg.github.git_timeout)
    github_client = GitHubClient(token=cfg.github.gh_token, proxy=cfg.github.proxy)

    repo_manager = RepositoryManager(analyzer, reporter, cfg)

    proposal_tracker = ProposalTracker(
        analyzer=analyzer,
        git_client=git_client,
        clock=lambda: get_now(cfg.get_timezone()),
        language=cfg.analysis.language,
        github_client=github_client,
    )

    return cfg, markpost_client, repo_manager, proposal_tracker, reporter


async def resolve_runtime_config(file_cfg: Config) -> Config:
    """Seed the DB config blob from the file config, then build the runtime config.

    The file is a one-time seed + infra provider; after the first run the blob
    is the source of truth, so the returned config reflects DB edits made via
    the web UI rather than later file changes.
    """
    from .config_store import (
        build_runtime_config,
        load_app_config,
        migrate_blob_schema,
        seed_app_config_if_needed,
        seed_lists_if_needed,
    )

    await seed_app_config_if_needed(file_cfg.model_dump(mode="json"))
    await migrate_blob_schema()
    await seed_lists_if_needed(file_cfg)
    loaded = await load_app_config()
    if loaded is None:
        return file_cfg
    blob_data, _ = loaded
    return build_runtime_config(
        blob_data,
        {
            "data_dir": file_cfg.data_dir,
            "workspace_dir": file_cfg.workspace_dir,
            "observability": file_cfg.observability.model_dump(mode="json"),
        },
    )
