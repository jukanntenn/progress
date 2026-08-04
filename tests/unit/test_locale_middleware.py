"""Unit tests for the API LocaleMiddleware (Feature 7)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from progress.api.middleware import LocaleMiddleware
from progress.config.root import CoreConfig
from progress.utils.i18n import get_locale, set_locale


async def _noop_app(scope: Any, receive: Any, send: Any) -> None:
    """Minimal ASGI app stub used only to satisfy LocaleMiddleware's constructor."""
    return


def _app_with_cfg(cfg: Any | None = None) -> SimpleNamespace:
    """Build a minimal ``app`` object exposing ``app.state.cfg`` (mirrors how the
    FastAPI lifespan populates it). When ``cfg`` is None, state has no cfg attr,
    matching the zero-config / not-yet-started case."""
    state = SimpleNamespace()
    if cfg is not None:
        state.cfg = cfg
    return SimpleNamespace(state=state)


async def _run(app_mw, scope_overrides: dict[str, object] | None = None) -> str:
    scope: dict[str, object] = {"type": "http", "headers": [], "app": _app_with_cfg()}
    if scope_overrides:
        scope.update(scope_overrides)

    received: dict[str, str] = {}

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        pass

    async def inner_app(s, r, w):
        received["locale"] = get_locale()

    app_mw._app = inner_app  # type: ignore[attr-defined]
    await app_mw(scope, receive, send)
    return received["locale"]


async def test_accept_language_negotiates_locale() -> None:
    mw = LocaleMiddleware(app=_noop_app)
    locale = await _run(mw, {"headers": [(b"accept-language", b"zh-hans")]})
    assert locale == "zh-hans"


async def test_falls_back_to_en_when_unsupported() -> None:
    mw = LocaleMiddleware(app=_noop_app)
    locale = await _run(mw, {"headers": [(b"accept-language", b"fr-FR")]})
    # fr-FR has no catalog installed → falls back to the default ('en').
    assert locale == "en"


async def test_falls_back_to_en_when_no_header() -> None:
    mw = LocaleMiddleware(app=_noop_app)
    locale = await _run(mw)
    assert locale == "en"


async def test_configured_language_wins_over_accept_language() -> None:
    """Regression: when ``cfg.language`` is an explicit non-default choice it
    must win over the browser's Accept-Language, so notifications / API-rendered
    content honour the configured locale (the fix for "notifications arrived in
    English despite zh-Hans being configured")."""

    mw = LocaleMiddleware(app=_noop_app)
    cfg = CoreConfig(language="zh-hans")
    locale = await _run(
        mw,
        {
            "headers": [(b"accept-language", b"en")],
            "app": _app_with_cfg(cfg),
        },
    )
    assert locale == "zh-hans"


async def test_default_config_falls_back_to_accept_language() -> None:
    """When the configured language is still the default ('en'), the browser's
    Accept-Language should drive the locale (dev/zero-config behaviour)."""

    mw = LocaleMiddleware(app=_noop_app)
    cfg = CoreConfig(language="en")
    locale = await _run(
        mw,
        {
            "headers": [(b"accept-language", b"zh-hans")],
            "app": _app_with_cfg(cfg),
        },
    )
    assert locale == "zh-hans"


async def test_non_http_scope_passes_through() -> None:
    mw = LocaleMiddleware(app=_noop_app)
    set_locale("en")
    scope = {"type": "lifespan", "headers": []}

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        pass

    called = False

    async def inner_app(s, r, w):
        nonlocal called
        called = True

    mw._app = inner_app  # type: ignore[attr-defined]
    await mw(scope, receive, send)
    assert called
