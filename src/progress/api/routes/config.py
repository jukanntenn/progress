"""Config endpoints (spec 12).

Three Web-class concerns surfaced over HTTP:

- ``GET /api/v1/config`` — full config dump in plaintext (secret fields are
  real values; the frontend masks them with ``type="password"``).
- ``GET /api/v1/config/schema`` — per-section JSON Schemas for the frontend
  config editor (internal fields stripped).
- ``PUT /api/v1/config/{section}`` — write a section's payload after Pydantic
  validation (atomic single-row upsert; a failed validation returns 422 and
  leaves the DB untouched).
- ``POST /api/v1/config/reload`` — re-read DB config into ``app.state.cfg``
  so config edits take effect without a restart.

Plaintext round-trip (spec 02 redesign): the DB stores normalized plaintext;
``model_validate`` validates on write; ``model_dump`` re-normalizes on store.
No sentinel masking anywhere in the chain.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ValidationError

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
from progress.db.models import User
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
    """Return ``{core, plugins}`` in plaintext (internal fields stripped)."""
    all_cfg = await get_all_config()
    core_data = all_cfg.get("core", {})
    plugins = {k: v for k, v in all_cfg.items() if k != "core"}
    try:
        CoreConfig.model_validate(core_data)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=f"core config corrupted: {e}") from e
    for name, plugin_data in plugins.items():
        model = _get_section_model(name)
        if model is None:
            continue
        try:
            model.model_validate(plugin_data)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=f"plugin '{name}' config corrupted: {e}") from e
    core_public = _strip_internal_fields(core_data)
    return AllConfigResponse(core=core_public, plugins=plugins)


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
    user: Annotated[User, Depends(get_current_user)],
) -> ConfigSectionResponse:
    """Validate ``data`` against the section's Pydantic model and upsert it."""
    if _get_section_model(section) is None:
        raise HTTPException(
            status_code=404,
            detail=f"unknown config section: {section}",
        )
    try:
        await set_config(section, body.data)
    except ConfigException as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if section == "core":
        db_core = await get_config("core")
        if db_core:
            try:
                request.app.state.cfg = merge_db_config(request.app.state.cfg, db_core)
            except Exception as e:
                logger.warning("config refresh after PUT failed; keeping current cfg: %s", e)

    record_business_event(
        "progress.config.updated",
        attributes={"section": section, "user": user.username},
    )

    fresh = await get_config(section)
    if section == "core":
        fresh = _strip_internal_fields(fresh)
    return ConfigSectionResponse(section=section, data=fresh)


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


def _get_section_model(section: str) -> type[BaseModel] | None:
    """Return the section's Pydantic config model; ``None`` if unknown."""
    if section == "core":
        from progress.config.root import CoreConfig  # noqa: PLC0415

        return CoreConfig
    integration_cls = discover_integrations().get(section)
    if integration_cls is None:
        return None
    config_schema = getattr(integration_cls, "config_schema", None)
    return config_schema if isinstance(config_schema, type) and issubclass(config_schema, BaseModel) else None


def _strip_internal_fields(core_data: dict) -> dict:  # ty:ignore[missing-type-argument]
    """从 GET 返回的 core 数据中移除内部字段（前端不可见）。"""
    out = dict(core_data)
    out.pop("state_home", None)
    auth = out.get("auth")
    if isinstance(auth, dict):
        auth = dict(auth)
        auth.pop("secret_key", None)
        auth.pop("initial_admin_password", None)
        out["auth"] = auth
    return out


__all__ = ["router"]
