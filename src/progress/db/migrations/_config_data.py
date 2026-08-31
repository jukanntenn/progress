"""启动时自动修复 config 表中的已知坏数据结构。

幂等、安全：只修复已知的坏结构，对正常数据无影响。在 init_db 之后、
apply_db_and_seed 之前调用，确保配置加载时数据已是合法结构。

文件名带 ``_`` 前缀：tortoise 的 MigrationLoader 会扫描本目录并把每个
模块当作 schema 迁移（``tortoise/migrations/loader.py`` 要求 ``Migration``
类），前缀 ``_``/``~`` 的模块被 loader 跳过，因此数据迁移可以安全地
与 schema 迁移共存于此目录。

修复函数对同一个 core dict 做内存内修改，最后统一一次 set_config 持久化。
单独逐条写入会在多条坏数据并存时互相阻塞（每条 set_config 都会校验整个
core 段），因此必须合并为单次写入。新增坏数据修复规则时，在此追加 fix
函数并注册到 migrate_config_data。
"""

from __future__ import annotations

import logging
from typing import Any

from progress.observability import report_severe

logger = logging.getLogger(__name__)


async def migrate_config_data() -> int:
    """扫描并修复所有 section 的已知坏数据，返回总修复数。"""
    from progress.db import get_config, set_config  # noqa: PLC0415

    total = await _fix_repo_deprecated_fields()

    core = await get_config("core")
    if isinstance(core, dict):
        fixed = _fix_core_bugsink(core) + _fix_core_recipient(core)
        if fixed:
            try:
                await set_config("core", core)
            except Exception as e:
                logger.error("config data migration: failed to persist core fixes: %s", e)
                report_severe(e)
                return total
            total += fixed
    if total:
        logger.info("config data migration: fixed %d field(s)", total)
    return total


async def _fix_repo_deprecated_fields() -> int:
    """剥离 repo 段中已被模型移除的废弃字段（如 stale-reenabled 三个键）。"""
    from progress.db import get_config, set_config  # noqa: PLC0415
    from progress.integrations.base import strip_unknown_config_keys  # noqa: PLC0415
    from progress.integrations.repo.config import RepoIntegrationConfig  # noqa: PLC0415

    repo = await get_config("repo")
    if not isinstance(repo, dict):
        return 0
    cleaned, removed = strip_unknown_config_keys(repo, RepoIntegrationConfig)
    if not removed:
        return 0
    try:
        await set_config("repo", cleaned)
    except Exception as e:
        logger.error("config data migration: failed to persist repo fixes: %s", e)
        report_severe(e)
        return 0
    logger.warning("migrated repo config: removed deprecated keys %s", removed)
    return len(removed)


def _fix_core_bugsink(core: dict[str, Any]) -> int:
    """修复 core.observability.bugsink: list[{...}] → 单对象 {...}。"""
    observability = core.get("observability")
    if not isinstance(observability, dict):
        return 0
    bugsink = observability.get("bugsink")
    if not isinstance(bugsink, list):
        return 0
    observability["bugsink"] = bugsink[0] if bugsink else {}
    logger.warning("migrated core.observability.bugsink: list[%d] → object", len(bugsink))
    return 1


def _fix_core_recipient(core: dict[str, Any]) -> int:
    """修复 core.notification.channels[*].recipient: 过滤非字符串元素。"""
    notification = core.get("notification")
    if not isinstance(notification, dict):
        return 0
    channels = notification.get("channels", [])
    if not isinstance(channels, list):
        return 0
    fixed = 0
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        recipient = ch.get("recipient")
        if not isinstance(recipient, list):
            continue
        cleaned = [r for r in recipient if isinstance(r, str)]
        if len(cleaned) != len(recipient):
            ch["recipient"] = cleaned
            fixed += 1
            logger.warning(
                "migrated core.notification.channels recipient: %d → %d items",
                len(recipient),
                len(cleaned),
            )
    return fixed


__all__ = ["migrate_config_data"]
