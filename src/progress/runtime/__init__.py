"""Application plugins: the composition tree as data (PRFC 2026-08-31 phase 1).

Every capability is a kernel plugin; ``compose_base`` is the single source of
ordering knowledge, expressed as service dependencies rather than sequencing
code. Entry ids are stable contract — phase-four patch layers target rows by
id, so ids are frozen here.
"""

from __future__ import annotations

from progress.kernel import Entry
from progress.runtime.ai import make_ai_entry
from progress.runtime.auth import make_auth_entry
from progress.runtime.config import make_config_entry
from progress.runtime.db import make_db_entry
from progress.runtime.git_proxy import make_git_proxy_entry
from progress.runtime.http import make_http_entry
from progress.runtime.i18n import make_i18n_entry
from progress.runtime.integrations import make_integrations_entry
from progress.runtime.notifications import make_notifications_entry
from progress.runtime.runner import make_runner_entry
from progress.runtime.scheduled_run import make_scheduled_run_entry
from progress.runtime.scheduler import make_scheduler_entry
from progress.runtime.telemetry import (
    make_telemetry_bugsink_entry,
    make_telemetry_entry,
    make_telemetry_logfile_entry,
    make_telemetry_otel_entry,
)
from progress.runtime.webserver import make_webserver_entry

BASE_ENTRY_IDS = (
    "db",
    "config",
    "telemetry",
    "telemetry-otel",
    "telemetry-bugsink",
    "telemetry-logfile",
    "ai",
    "i18n",
    "git-proxy",
    "auth",
    "http",
    "notifications",
    "scheduler",
)
SERVE_EXTRA_IDS = ("integrations", "runner", "scheduled-run", "webserver")


def compose_base(cfg, *, config_path: str | None = None, component: str = "cli") -> list[Entry]:
    """The shared tree both entry points boot (phase 3: hub + three backends)."""
    return [
        make_db_entry(cfg),
        make_config_entry(cfg, config_path),
        make_telemetry_entry(),
        make_telemetry_otel_entry(),
        make_telemetry_bugsink_entry(component),
        make_telemetry_logfile_entry(),
        make_ai_entry(),
        make_i18n_entry(),
        make_git_proxy_entry(),
        make_auth_entry(),
        make_http_entry(),
        make_notifications_entry(),
        make_scheduler_entry(),
    ]


def compose_serve(cfg, *, config_path: str | None = None, app=None) -> list[Entry]:
    """The API tree: base plus auth bootstrap and the FastAPI shell."""
    if app is None:
        raise ValueError("compose_serve requires the FastAPI app (the ASGI lifespan provides it)")
    return [
        *compose_base(cfg, config_path=config_path, component="api"),
        make_integrations_entry(),
        make_runner_entry(),
        make_scheduled_run_entry(),
        make_webserver_entry(app),
    ]


def compose_users(cfg) -> list[Entry]:
    """The minimal tree user-management commands need: DB only."""
    return [make_db_entry(cfg)]


__all__ = ["BASE_ENTRY_IDS", "SERVE_EXTRA_IDS", "compose_base", "compose_serve", "compose_users"]
