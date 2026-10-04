"""webserver entry: own the FastAPI app, instrument it, wire ``app.state``.

The ASGI lifespan protocol hands the app to the lifespan callable, which is
how the composition reaches it — the app object is passed by closure from
``compose_serve`` and becomes the ``ctx.webServer`` service value. Route
registration stays eager at app construction in phase 1; the
``register_router`` seam is phase 3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from progress.kernel import Definition, Entry
from progress.observability import instrument_fastapi_app

if TYPE_CHECKING:
    from fastapi import FastAPI


class WebServerService(Definition):
    service_name = "webServer"


def make_webserver_entry(app: FastAPI) -> Entry:
    async def _apply(ctx: Any, config: Any) -> None:
        instrument_fastapi_app(app)
        app.state.ctx = ctx
        app.state.cfg = ctx.config
        app.state.session = ctx.http
        ctx.provide(WebServerService, app)

    return Entry(id="webserver", plugin=_apply, inject=["config", "telemetry", "http", "authReady"])
