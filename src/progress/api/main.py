"""ASGI entry point: ``uvicorn progress.api.main:app``.

Construction is deferred to :func:`progress.api.create_app` so the import
itself never crashes (spec 12 fix for the legacy ``main.py:3`` bug). uvicorn
will import this module and use ``app`` directly.
"""

from __future__ import annotations

from progress.api import create_app

app = create_app()

__all__ = ["app"]
