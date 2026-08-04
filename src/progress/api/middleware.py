"""ASGI middleware stack (spec 12).

Order matters (Starlette wraps in reverse-registration order, so the order
listed here is the order requests hit them):

1. :class:`GZipMiddleware` — compression (outermost).
2. :class:`SecureASGIMiddleware` — CSP/HSTS/X-Frame-Options etc.
3. :class:`CorrelationIdMiddleware` — request ID + sentry-sdk integration.
4. :class:`CORSMiddleware` — **dev only** (``PROGRESS_DEV_CORS=1``).
5. :class:`TrustedHostMiddleware` — added by caller when not bound to loopback.

Per spec 12:
- CORS is dead code in production (Caddy single-origin) — gated by env var.
- HSTS is on by default in ``secure``; the reverse proxy terminates TLS so the
  API just emits the header (browser only honors it on HTTPS responses).
"""

from __future__ import annotations

import logging

from asgi_correlation_id import CorrelationIdMiddleware
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from secure import Secure
from secure.middleware import SecureASGIMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from progress.config.root import CoreConfig
from progress.utils.i18n import negotiate_locale, set_locale

logger = logging.getLogger(__name__)

DEFAULT_CORS_ALLOW_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


class LocaleMiddleware:
    """Per-request locale → ``set_locale`` (ContextVar).

    Priority: an explicitly configured ``cfg.language`` (non-default) wins over
    the browser's Accept-Language; otherwise Accept-Language (negotiated) →
    ``cfg.language`` → 'en'. Runs innermost so every request handler renders in
    the request's locale (notification/email templates that call ``_()`` pick
    this up).
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        app = scope.get("app")
        state = getattr(app, "state", None)
        cfg = getattr(state, "cfg", None) if state is not None else None
        configured = cfg.language if isinstance(cfg, CoreConfig) else "en"
        headers = dict(scope.get("headers", []))
        accept = headers.get(b"accept-language", b"").decode("latin-1", "ignore")
        # Configured language wins when it is an explicit (non-default) choice;
        # otherwise fall back to the browser's Accept-Language.
        if configured and configured != "en":
            locale = configured
            source = "config"
        else:
            locale = negotiate_locale(accept) if accept else configured
            source = "accept-language" if accept else "default"
        set_locale(locale)
        # Trace WHY a request rendered in a given locale — without this the
        # configured-vs-header decision was unverifiable in production, making
        # i18n bugs ("notifications arrived in English") impossible to root-cause.
        logger.debug(
            "locale resolved",
            extra={
                "locale": locale,
                "locale_source": source,
                "configured_language": configured,
                "accept_language": accept[:64] or None,
            },
        )
        await self._app(scope, receive, send)


def register_middleware(app: FastAPI, *, dev_cors: bool = False) -> None:
    """Attach the spec 12 middleware stack to ``app``."""
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    secure_headers = Secure.with_default_headers()
    app.add_middleware(SecureASGIMiddleware, secure=secure_headers)

    app.add_middleware(CorrelationIdMiddleware)

    if dev_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=DEFAULT_CORS_ALLOW_ORIGINS,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )
        logger.info("CORS middleware enabled (dev mode): %s", DEFAULT_CORS_ALLOW_ORIGINS)
    else:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])

    # Innermost: set per-request locale so handlers/templates render localized.
    app.add_middleware(LocaleMiddleware)


__all__ = ["DEFAULT_CORS_ALLOW_ORIGINS", "LocaleMiddleware", "register_middleware"]
