"""FastAPI dependencies (spec 12).

``Depends``-style accessors that pull process-singleton state off the app.
Routes import these so they don't reach into ``app.state`` directly — easier
to mock in tests and easier to refactor.
"""

from __future__ import annotations

import aiohttp
from fastapi import Depends, Request

from progress.config.root import CoreConfig


def get_config(request: Request) -> CoreConfig:
    """Return the lifespan-loaded :class:`CoreConfig`.

    Raises if the lifespan hasn't run yet (e.g. test misconfiguration).
    """
    cfg = getattr(request.app.state, "cfg", None)
    if cfg is None:
        raise RuntimeError("CoreConfig not initialized; lifespan did not run")
    return cfg


def get_session(request: Request) -> aiohttp.ClientSession:
    """Return the lifespan-owned aiohttp session."""
    session = getattr(request.app.state, "session", None)
    if session is None:
        raise RuntimeError("aiohttp.ClientSession not initialized; lifespan did not run")
    return session


ConfigDep = Depends(get_config)
SessionDep = Depends(get_session)


__all__ = ["ConfigDep", "SessionDep", "get_config", "get_session"]
