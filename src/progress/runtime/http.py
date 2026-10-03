"""http entry: the shared aiohttp session → ``ctx.http``.

Injects ``telemetry``/``telemetryOtel`` to declare the ordering invariant:
the OTel aiohttp instrumentor must be armed before any session is created
(spec 04) — previously a comment in a hand-written lifespan, now a
dependency.
"""

from __future__ import annotations

import aiohttp

from progress.kernel import Definition, Entry
from progress.utils.http import session_factory


class HttpService(Definition):
    service_name = "http"


def make_http_entry() -> Entry:
    async def _apply(ctx, config) -> None:
        cfg = ctx.config
        cm = session_factory(proxy=cfg.github.proxy or None)
        session = await cm.__aenter__()
        ctx.provide(HttpService, session)

        async def _close() -> None:
            await cm.__aexit__(None, None, None)

        ctx.effect(_close)

    return Entry(id="http", plugin=_apply, inject=["config", "telemetry", "telemetryOtel"])


def session_value(ctx) -> aiohttp.ClientSession:
    session = ctx.get(HttpService)
    if session is None:
        raise RuntimeError("http service not available; inject http before using the session")
    return session
