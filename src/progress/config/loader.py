"""Configuration loader.

Loading order per spec 02:
1. Ansible-class file (``config.toml``) supplies ``state_home`` (and only that).
2. DB ``config`` table (section="core") supplies the rest of ``CoreConfig``.
3. ``config.db.toml`` (if present) seeds the DB on startup; DB values win over seed.

For the initial implementation we collapse steps 2-3 into a single ``load_config``
call that returns a fully populated ``CoreConfig``: Ansible file → DB → seed merge.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import ValidationError
import tomlkit

from progress.config.root import CoreConfig
from progress.db import get_config, set_config
from progress.errors import ConfigException


def load_config(config_path: str | None = None) -> CoreConfig:
    """Load configuration from the Ansible-class file.

    - ``config_path`` is ``None`` → return defaults (zero config).
    - ``config_path`` points to a missing file → raise ``ConfigException``.
    - ``config_path`` points to a valid file → parse + validate.

    The Ansible-class file only carries ``state_home`` per spec 02. The remaining
    Web-class fields come from the DB and are merged at runtime by
    :func:`merge_db_config`.
    """
    if config_path is None:
        return CoreConfig()
    path = Path(config_path)
    if not path.exists():
        raise ConfigException(f"config file not found: {config_path}")
    try:
        data = tomlkit.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ConfigException(f"failed to parse config file: {e}") from e
    try:
        return CoreConfig.model_validate(data)
    except ValidationError as e:
        lines = ["Configuration validation failed:"]
        for err in e.errors():
            loc = " -> ".join(str(item) for item in err["loc"])
            lines.append(f"  - {loc}: {err['msg']}")
        raise ConfigException("\n".join(lines)) from e


def find_seed_file(config_path: str | None) -> Path | None:
    """Locate ``config.db.toml`` next to the Ansible config file."""
    if config_path is None:
        return None
    seed = Path(config_path).parent / "config.db.toml"
    return seed if seed.exists() else None


def load_seed(seed_path: Path) -> dict[str, Any]:
    """Load seed TOML into a dict of section → data."""
    try:
        data = tomlkit.loads(seed_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise ConfigException(f"failed to parse seed file {seed_path}: {e}") from e
    return _unwrap_seed(data)


def _unwrap_seed(data: dict[str, Any]) -> dict[str, Any]:
    """Extract per-section payloads from seed file.

    The seed file mirrors the ``config`` table layout::

        [core]
        language = "en"
        [core.github]
        gh_token = "..."

        [repo]
        [[repo.repos]]
        url = "..."

    Returns ``{"core": {...}, "repo": {...}}``.
    """
    return {key: value for key, value in data.items() if isinstance(value, dict)}


async def seed_from_file(config_path: str | None) -> None:
    """Persist every section from ``config.db.toml`` into the DB config table.

    Per spec 02 §"DB 种子约定": on every startup the seed file is re-imported
    into the DB with key-level merge priority ``DB > seed`` — seed values only
    fill keys the DB doesn't already have, so Web UI edits survive a restart.
    Covers both the ``[core]`` section and plugin sections (``[repo]`` /
    ``[changelog]`` / ``[proposal]``), so each integration's ``setup`` can read
    its own section via :func:`progress.db.get_config`.

    Validation is delegated to :func:`progress.db.set_config` →
    :func:`progress.db._validate_section` (core passes through; plugins are
    validated against their registered ``config_schema``). A failing section is
    logged and skipped so one bad section does not abort the whole seed import.
    """

    logger = logging.getLogger(__name__)

    if config_path is None:
        return
    seed_path = find_seed_file(config_path)
    if seed_path is None:
        return
    try:
        seed = load_seed(seed_path)
    except Exception as e:
        logger.warning("failed to load seed file %s: %s", seed_path, e)
        return
    for section, seed_data in seed.items():
        if not isinstance(seed_data, dict) or not seed_data:
            continue
        db_data = await get_config(section)
        merged: dict[str, Any] = {**seed_data, **db_data}
        try:
            await set_config(section, merged)
        except Exception as e:
            logger.warning("failed to seed config section '%s': %s", section, e)


async def apply_db_and_seed(cfg: CoreConfig, config_path: str | None) -> CoreConfig:
    """Merge seed-file + DB-stored core config into ``cfg`` (spec 02).

    First persists every seed-file section into the DB (so integrations can
    read their own section), then builds the in-memory ``CoreConfig`` from the
    ``[core]`` section. Priority: DB > seed > ansible-file defaults. The seed
    file sits next to the ansible config (``config.db.toml``) and only fills
    keys the DB doesn't have - so production (no seed file) just uses DB, while
    tests/first-deploy use the seed file as the initial source of truth.

    Shared by CLI and API lifespan; both entry points need the same merge logic.
    """

    logger = logging.getLogger(__name__)

    await seed_from_file(config_path)

    db_core = await get_config("core")
    seed_core = _load_seed_core(config_path)
    merged_core: dict[str, Any] = {}
    if seed_core:
        merged_core.update(seed_core)
    if db_core:
        merged_core.update(db_core)
    if not merged_core:
        return cfg
    try:
        return merge_db_config(cfg, merged_core)
    except Exception as e:
        logger.warning("failed to merge DB/seed core config; using ansible-file values: %s", e)
        return cfg


def _load_seed_core(config_path: str | None) -> dict[str, Any]:
    """Load the ``[core]`` section from ``config.db.toml`` if present."""

    logger = logging.getLogger(__name__)

    if config_path is None:
        return {}
    seed_path = find_seed_file(config_path)
    if seed_path is None:
        return {}
    try:
        seed = load_seed(seed_path)
    except Exception as e:
        logger.warning("failed to load seed file %s: %s", seed_path, e)
        return {}
    core = seed.get("core")
    if not isinstance(core, dict):
        return {}
    return core


def merge_db_config(cfg: CoreConfig, db_core: dict[str, Any]) -> CoreConfig:
    """Merge DB-stored core section into a CoreConfig built from the Ansible file.

    明文方案：DB 存的是规范化明文 dict，直接 model_validate。
    state_home 始终保留 ansible-file 的值（Ansible-owned）。
    """
    if not db_core:
        return cfg
    merged = dict(db_core)
    merged["state_home"] = cfg.state_home
    return CoreConfig.model_validate(merged)
