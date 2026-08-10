"""Database initialization, connection management, and config-table CRUD.

Per spec 03:
- Use tortoise-orm's built-in migrations (per-app ``migrations/`` directories).
- ``init_db`` initializes the connection and applies migrations.
- Config table read/write API (spec 02) is implemented here on top of the
  ``Config`` tortoise model.

Config writes (``set_config``) validate the submitted payload with the
section's Pydantic model before the upsert happens — a failed validation
raises ``ConfigException`` and leaves the DB untouched. Data is stored as a
normalized plaintext dict (SecretStr unwrapped), so the runtime can load it
back with a plain ``model_validate``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr, ValidationError
from tortoise import Tortoise
from tortoise.connection import get_connection
from tortoise.migrations.executor import MigrationExecutor, MigrationTarget

from progress.db.models.config import Config
from progress.db.tortoise_config import build_db_url, build_tortoise_config
from progress.errors import ConfigException
from progress.integrations.registry import discover_integrations
from progress.observability import record_business_event

logger = logging.getLogger(__name__)


async def init_db(state_home: str, *, run_migrations: bool = True) -> None:
    """Initialize the DB connection and apply migrations.

    The DB file lives at ``<state_home>/progress.db`` (spec 02 derived path).
    """
    db_url = build_db_url(state_home)
    Path(state_home).mkdir(parents=True, exist_ok=True)
    config = build_tortoise_config(db_url)
    await Tortoise.init(config=config, _enable_global_fallback=True)
    logger.info("Database initialized: %s", state_home)
    if run_migrations:
        await _apply_migrations(config)


async def _apply_migrations(config: dict[str, Any]) -> None:
    """Apply pending tortoise migrations using the existing connection.

    Per-migration error handling: if a migration fails with "already exists"
    or "duplicate column" (bootstrap case where tables were created outside
    the migration system), it is fake-applied (marked as applied without
    running) so subsequent migrations can proceed. All other errors are logged
    and recorded as metrics but never raised - the program degrades, never
    crashes (spec 03 invariant).
    """

    apps_cfg = config.get("apps", {})
    for app_label, app_config in apps_cfg.items():
        connection_name = app_config.get("default_connection", "default")
        connection = get_connection(connection_name)
        if connection is None:
            logger.warning(
                "no connection '%s' for app '%s'; skipping migrations",
                connection_name,
                app_label,
            )
            continue

        executor = MigrationExecutor(connection, {app_label: app_config})
        try:
            await executor.loader.build_graph()
            await executor.recorder.ensure_schema(executor._schema_editor(atomic=False))  # noqa: SLF001
            applied = set(await executor.recorder.applied_migrations())

            migration_names = sorted(executor.loader.graph.nodes)
            for mkey in migration_names:
                name = mkey.name
                already = any(k.app_label == app_label and k.name == name for k in applied)
                if already:
                    continue

                target = [MigrationTarget(app_label=app_label, name=name)]
                try:
                    await executor.migrate(target)
                    logger.info("migration %s/%s applied", app_label, name)
                    record_business_event(
                        "progress.db.migration_applied",
                        attributes={"app": app_label, "name": name},
                    )
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg or "duplicate column" in msg:
                        logger.info(
                            "migration %s/%s already in effect; fake-applying",
                            app_label,
                            name,
                        )
                        await executor.migrate(target, fake=True)
                        record_business_event(
                            "progress.db.migration_bootstrap",
                            attributes={"app": app_label, "name": name},
                        )
                    else:
                        logger.warning(
                            "migration %s/%s failed: %s; continuing",
                            app_label,
                            name,
                            e,
                        )
                        record_business_event(
                            "progress.db.migration_failed",
                            attributes={"app": app_label, "name": name, "error": str(e)[:200]},
                        )
        except Exception as e:
            logger.warning(
                "migration setup failed for app %s: %s; continuing",
                app_label,
                e,
            )
            record_business_event(
                "progress.db.migration_failed",
                attributes={"app": app_label, "name": "setup", "error": str(e)[:200]},
            )


async def close_db() -> None:
    """Close all DB connections."""
    await Tortoise.close_connections()
    logger.info("Database connections closed")


async def get_config(section: str) -> dict[str, Any]:
    """Read a config section's payload. Returns ``{}`` if absent."""

    row = await Config.get_or_none(section=section)
    if row is None:
        return {}
    data = row.data
    return dict(data) if isinstance(data, dict) else {}


async def set_config(section: str, data: dict[str, Any]) -> None:
    """Upsert a config section after Pydantic validation.

    校验失败抛 ConfigException（调用方转 422），DB 不变。
    core 段的内部字段（state_home / auth.secret_key / auth.initial_admin_password）
    始终保留 DB 原值，不从前端提交覆盖。
    """
    if not isinstance(data, dict):
        raise ConfigException(f"config section '{section}' payload must be a JSON object")

    model = _get_section_model(section)
    if model is None:
        raise ConfigException(f"unknown config section: {section}")

    if section == "core":
        data = _preserve_internal_fields(data, await get_config("core"))

    from progress.config.schema import get_config_json_schema  # noqa: PLC0415

    schema = get_config_json_schema().get(section, {})
    data = _normalize_nulls(data, schema, schema)

    try:
        validated = model.model_validate(data)
    except ValidationError as e:
        raise ConfigException(_format_validation_errors(section, e)) from e

    payload = _dump_plaintext(validated)
    await Config.update_or_create(section=section, defaults={"data": payload})


def _get_section_model(section: str) -> type[BaseModel] | None:
    """Return section 对应的 Pydantic 配置模型，未知 section 返回 None。"""
    if section == "core":
        from progress.config.root import CoreConfig  # noqa: PLC0415

        return CoreConfig
    try:
        integration_cls = discover_integrations().get(section)
    except Exception:
        return None
    if integration_cls is None:
        return None
    config_schema = getattr(integration_cls, "config_schema", None)
    return config_schema if isinstance(config_schema, type) and issubclass(config_schema, BaseModel) else None


def _format_validation_errors(section: str, e: ValidationError) -> str:
    """把 Pydantic ValidationError 格式化为前端可读的字符串。

    errors() 返回 [{loc, msg, type, ...}]，loc 是元组如 ('github', 'gh_token')。
    转为 'github.gh_token: <msg>' 形式，多条用换行分隔。
    """
    lines = [f"invalid config for section '{section}':"]
    for err in e.errors():
        loc = ".".join(str(item) for item in err["loc"])
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def _dump_plaintext(model: BaseModel) -> dict[str, Any]:
    """把校验后的 Pydantic 模型 dump 为纯 dict（SecretStr 解包为明文）。

    model_dump(mode="python") 保留 SecretStr 对象（不可直接 JSON 序列化），
    需递归解包为 get_secret_value()。输出是 coercion 后的规范化值
    （如 "3" -> int 3），保证 DB 存储的是干净数据。
    """
    return _unwrap_secrets(model.model_dump(mode="python"))


def _unwrap_secrets(obj: Any) -> Any:
    """递归把 SecretStr 对象解包为明文字符串。"""
    if isinstance(obj, dict):
        return {k: _unwrap_secrets(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_unwrap_secrets(item) for item in obj]
    if isinstance(obj, SecretStr):
        return obj.get_secret_value()
    return obj


# core 段的内部字段路径（所有者=系统/Ansible，前端不可编辑）
_CORE_INTERNAL_PATHS = {
    "state_home": (),  # 顶层
    "secret_key": ("auth",),
    "initial_admin_password": ("auth",),
}


def _preserve_internal_fields(submitted: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any]:
    """把 DB 中的内部字段原值注入提交数据，确保前端不提交时保留。

    这些字段不出现在可编辑 JSON Schema 里（前端不可见），所以前端
    提交的 data 里不会包含它们。从 DB 读取原值注入，校验时 model_validate
    会接受它们（因为是合法值），dump 后原样存回 DB。
    """
    out = dict(submitted)
    for field, path in _CORE_INTERNAL_PATHS.items():
        cursor_existing = existing
        for key in path:
            cursor_existing = cursor_existing.get(key, {}) if isinstance(cursor_existing, dict) else {}
        if isinstance(cursor_existing, dict) and field in cursor_existing:
            if path:
                out.setdefault(path[0], {})
                if isinstance(out.get(path[0]), dict):
                    out[path[0]][field] = cursor_existing[field]
            else:
                out[field] = cursor_existing[field]
    return out


def _normalize_nulls(data: Any, schema: dict[str, Any], root: dict[str, Any]) -> Any:
    """把 string 类型字段的 null 值转为空串（前端 RJSF 空输入的兜底）。

    基于 JSON Schema 的 type:"string" 递归（非 Pydantic model 类型），
    $ref 在每步解析（root 是含 $defs 的 section schema）。
    SecretStr 在 schema 里也是 type:"string"（+format:password），一并覆盖。
    """
    schema = _resolve_ref(schema, root)
    if not isinstance(data, dict):
        return data
    props = schema.get("properties", {})
    out: dict[str, Any] = {}
    for key, val in data.items():
        prop_schema = _resolve_ref(props.get(key, {}), root)
        if val is None and prop_schema.get("type") == "string":
            out[key] = ""
        elif isinstance(val, dict):
            out[key] = _normalize_nulls(val, prop_schema, root)
        elif isinstance(val, list):
            item_schema = _resolve_ref(prop_schema.get("items", {}), root)
            out[key] = [_normalize_nulls_list_item(item, item_schema, root) for item in val]
        else:
            out[key] = val
    return out


def _normalize_nulls_list_item(item: Any, item_schema: dict[str, Any], root: dict[str, Any]) -> Any:
    """处理 list item 的 null 容错（支持 discriminated union 与普通 object）。"""
    if not isinstance(item, dict):
        return item
    one_of = item_schema.get("oneOf")
    if one_of:
        discriminator = item_schema.get("discriminator", {}).get("propertyName", "type")
        item_type = item.get(discriminator)
        for member_ref in one_of:
            member_schema = _resolve_ref(member_ref, root)
            if member_schema.get("properties", {}).get(discriminator, {}).get("const") == item_type:
                return _normalize_nulls(item, member_schema, root)
        return item
    if item_schema.get("type") == "object":
        return _normalize_nulls(item, item_schema, root)
    return item


def _resolve_ref(node: Any, root: dict[str, Any]) -> dict[str, Any]:
    """解析 JSON Schema 的本地 $ref（如 "#/$defs/AuthConfig"）。

    node 形如 {"$ref": "#/$defs/AuthConfig"}，按 JSON Pointer 解析 root。
    """
    if isinstance(node, dict) and node.get("$ref"):
        ref = node["$ref"]
        if isinstance(ref, str) and ref.startswith("#/"):
            cursor: Any = root
            for part in ref[2:].split("/"):
                cursor = cursor.get(part, {}) if isinstance(cursor, dict) else {}
            return cursor if isinstance(cursor, dict) else node
    return node


async def get_all_config() -> dict[str, dict[str, Any]]:
    """Read every config section as ``{section: data}``."""

    out: dict[str, dict[str, Any]] = {}
    async for row in Config.all():
        data = row.data
        out[row.section] = dict(data) if isinstance(data, dict) else {}
    return out


__all__ = [
    "_dump_plaintext",
    "build_db_url",
    "build_tortoise_config",
    "close_db",
    "get_all_config",
    "get_config",
    "init_db",
    "set_config",
]
