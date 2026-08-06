"""Config endpoints (spec 12).

Three Web-class concerns surfaced over HTTP:

- ``GET /api/v1/config`` — full config dump with secrets masked (SecretStr
  serializes to ``********``).
- ``GET /api/v1/config/schema`` — per-section JSON Schemas for the frontend
  config editor.
- ``PUT /api/v1/config/{section}`` — write a section's payload after schema
  validation (atomic single-row upsert; legacy ``replace_*`` endpoints gone).
- ``POST /api/v1/config/reload`` — re-read DB config into ``app.state.cfg``
  so config edits take effect without a restart.

Per spec 02, SecretStr fields are automatically masked via ``model_dump(mode="json")``
when the data is round-tripped through a Pydantic model. No hand-written masking.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from progress.api.auth import get_current_user
from progress.api.routes._limiter import limiter
from progress.api.schemas import (
    AllConfigResponse,
    ConfigReloadResponse,
    ConfigSchemaResponse,
    ConfigSectionResponse,
    ConfigUpdateRequest,
    LanguageResponse,
    LanguageUpdateRequest,
    TestChannelResult,
    TestNotificationResponse,
)
from progress.cli.notifications.config import build_channels
from progress.cli.notifications.dispatcher import Dispatcher
from progress.cli.notifications.events import TestNotificationEvent
from progress.cli.notifications.renderer import JinjaRenderer
from progress.config.loader import merge_db_config
from progress.config.root import CoreConfig, _normalize_bcp47
from progress.config.schema import get_config_json_schema
from progress.db import get_all_config, get_config, set_config
from progress.errors import ConfigException
from progress.integrations.registry import discover_integrations
from progress.observability import record_business_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"], dependencies=[Depends(get_current_user)])


@router.get(
    "/config",
    response_model=AllConfigResponse,
    status_code=status.HTTP_200_OK,
)
async def get_all_sections() -> AllConfigResponse:
    """Return ``{core, plugins}`` with secrets masked (spec 02)."""
    all_cfg = await get_all_config()
    core_raw = all_cfg.get("core", {})
    plugins = {k: v for k, v in all_cfg.items() if k != "core"}

    core_masked = _mask_core_section(core_raw)
    for name, plugin_data in plugins.items():
        plugins[name] = _mask_plugin_section(name, plugin_data)
    return AllConfigResponse(core=core_masked, plugins=plugins)


@router.get(
    "/config/language",
    response_model=LanguageResponse,
    status_code=status.HTTP_200_OK,
)
async def get_language(request: Request) -> LanguageResponse:
    """Return the configured UI/notifications language (``core.language``).

    The SPA fetches this on boot so its initial locale matches the server
    config, closing the gap where the web UI stayed English even though
    ``core.language = zh-Hans`` was set (the SPA previously only honoured
    localStorage / the browser's Accept-Language).
    """
    cfg: CoreConfig = request.app.state.cfg
    return LanguageResponse(language=cfg.language)


@router.put(
    "/config/language",
    response_model=LanguageResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30 per minute")
async def set_language(body: LanguageUpdateRequest, request: Request) -> LanguageResponse:
    """Update ``core.language`` atomically (used by the language switcher).

    Merges the new value into the existing ``[core]`` section so the rest of
    the core config (tokens, markpost url, …) is preserved, then refreshes
    ``app.state.cfg`` so the LocaleMiddleware picks up the new language on the
    very next request — no restart needed.
    """
    new_language = _normalize_bcp47(body.language.strip()) if body.language else "en"
    core = await get_config("core")
    core = core or {}
    if core.get("language") == new_language:
        return LanguageResponse(language=new_language)
    core["language"] = new_language
    try:
        await set_config("core", core)
    except ConfigException as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    cfg: CoreConfig = request.app.state.cfg
    try:
        # Update only the language field on the live config — a full
        # ``merge_db_config(cfg, core)`` rebuild would overwrite any runtime-only
        # cfg state with DB defaults, and the old partial merge masked SecretStr
        # fields (model_dump mode="json"). ``model_copy(update=...)`` touches
        # only language, leaving secrets (and test-time overrides) intact.
        request.app.state.cfg = cfg.model_copy(update={"language": new_language})
    except Exception as e:
        logger.warning("language update merge failed; keeping current cfg: %s", e)
    record_business_event(
        "progress.config.language_changed",
        attributes={"language": new_language},
    )
    return LanguageResponse(language=new_language)


@router.get(
    "/config/schema",
    response_model=ConfigSchemaResponse,
    status_code=status.HTTP_200_OK,
)
async def get_schema() -> ConfigSchemaResponse:
    """Return per-section JSON Schemas for the frontend config editor."""
    return ConfigSchemaResponse(schemas=get_config_json_schema())


@router.put(
    "/config/{section}",
    response_model=ConfigSectionResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30 per minute")
async def put_section(
    section: str,
    body: ConfigUpdateRequest,
    request: Request,
) -> ConfigSectionResponse:
    """Validate ``data`` against the section's schema and upsert it."""
    if not _is_known_section(section):
        raise HTTPException(
            status_code=404,
            detail=f"unknown config section: {section}",
        )
    try:
        await set_config(section, body.data)
    except ConfigException as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    fresh = await get_config(section)
    masked = _mask_plugin_section(section, fresh) if section != "core" else _mask_core_section(fresh)
    return ConfigSectionResponse(section=section, data=masked)


@router.post(
    "/config/reload",
    response_model=ConfigReloadResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("30 per minute")
async def reload_config(request: Request) -> ConfigReloadResponse:
    """Re-read DB-stored core config and refresh ``app.state.cfg``."""
    cfg: CoreConfig = request.app.state.cfg
    db_core = await get_config("core")
    if db_core:
        try:
            request.app.state.cfg = merge_db_config(cfg, db_core)
        except Exception as e:
            logger.warning("config reload merge failed; keeping current cfg: %s", e)
            return ConfigReloadResponse(status="noop", section="core")
    return ConfigReloadResponse(status="ok", section="core")


@router.post(
    "/config/notifications/test",
    response_model=TestNotificationResponse,
    status_code=status.HTTP_200_OK,
)
@limiter.limit("3 per minute")
async def test_notifications(request: Request) -> TestNotificationResponse:
    """Send a test notification to all enabled channels; report per-channel results.

    Used by the config console to verify channel reachability. Renders a fixed
    i18n test message (localized per the request's Accept-Language via
    ``LocaleMiddleware``) and dispatches via the same ``Dispatcher`` the report
    pipeline uses.
    """
    cfg: CoreConfig = request.app.state.cfg
    session = getattr(request.app.state, "session", None)
    channels = build_channels(cfg.notification, session=session)
    if not channels:
        return TestNotificationResponse(results=[], summary="no_channels")
    event = TestNotificationEvent()
    renderer = JinjaRenderer(cfg)
    dispatcher = Dispatcher(channels, renderer)
    outcome = await dispatcher.dispatch(event)
    for r in outcome.results:
        record_business_event(
            "progress.notifications.test",
            attributes={"channel": r.channel, "ok": str(r.ok)},
        )
    results = [TestChannelResult(channel=r.channel, ok=r.ok, error=r.error) for r in outcome.results]
    summary = "ok" if outcome.ok else "partial_failure"
    return TestNotificationResponse(results=results, summary=summary)


def _is_known_section(section: str) -> bool:
    if section == "core":
        return True
    return section in discover_integrations()


def _mask_core_section(data: dict) -> dict:  # ty:ignore[missing-type-argument]
    """Validate ``data`` through ``CoreConfig`` so SecretStr fields auto-mask.

    Per spec 02, ``SecretStr.model_dump(mode="json")`` emits ``**********``
    automatically. We merge the DB data into a default CoreConfig dump first
    so that any missing keys get their defaults, then validate the result.
    """
    if not data:
        return CoreConfig().model_dump(mode="json")
    merged = _deep_merge(CoreConfig().model_dump(mode="json"), data)
    try:
        return CoreConfig.model_validate(merged).model_dump(mode="json")
    except Exception as e:
        logger.warning("core config validation failed; returning raw data: %s", e)
        return data


def _mask_plugin_section(name: str, data: dict) -> dict:  # ty:ignore[missing-type-argument]
    """Mask secrets in a plugin section using its registered config schema."""
    integration_cls = discover_integrations().get(name)
    if integration_cls is None:
        return data
    schema = getattr(integration_cls, "config_schema", None)
    if schema is None:
        return data
    try:
        validated = schema.model_validate(data)
        return validated.model_dump(mode="json")
    except Exception as e:
        logger.warning("plugin %s payload failed schema validation; returning raw: %s", name, e)
        return data


def _deep_merge(base: dict, overlay: dict) -> dict:  # ty:ignore[missing-type-argument]
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


__all__ = ["router"]
