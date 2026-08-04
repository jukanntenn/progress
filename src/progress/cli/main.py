"""Typer app + CLI command definitions (spec 05).

This is the CLI entry module: it owns the ``app`` Typer instance and the
``run`` / ``serve`` / ``users`` command registrations, plus the heavy imports
(``cli.core`` / ``config.loader`` / ``cli.users``) those commands need. It is
the only place these heavy modules are pulled in at module top level.

``progress.cli.__init__`` is intentionally minimal (a docstring only) so that
importing any ``progress.cli.*`` sub-module from the API path — notably
``config.root -> cli.notifications.config`` — does not eagerly drag in
``cli.core -> cli.lifespan -> config.loader``, which would form a circular
import and break ``from progress.api import create_app``. This mirrors the
pattern used by Typer / FastAPI / fastapi-cli themselves, where the Typer app
lives in a dedicated module (``main.py`` / ``cli.py``) and ``__init__.py``
stays empty.

Entry points:
    progress = "progress.cli.main:app"   (pyproject.toml console script)
    python -m progress                    (src/progress/__main__.py)
"""

from __future__ import annotations

import asyncio
import os

import typer
import uvicorn

from progress.cli.core import run as core_run
from progress.cli.users import users_app
from progress.config.loader import load_config
from progress.errors import ConfigException

app = typer.Typer(invoke_without_command=False, help="Progress: GitHub multi-repo project tracking tool.")

app.add_typer(users_app, name="users")


@app.command()
def run(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the Ansible-class config file."),
    trackers_only: bool = typer.Option(
        False, "--trackers-only", help="Run only tracker integrations (skip reports/notifications)."
    ),
) -> None:
    """Run the full tracking pipeline (all integrations)."""
    try:
        cfg = load_config(config)
    except ConfigException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2) from None

    outcome = asyncio.run(core_run(cfg, config_path=config, trackers_only=trackers_only))
    raise typer.Exit(code=outcome.exit_code)


@app.command()
def serve(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the Ansible-class config file."),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Start the API server (uvicorn)."""
    try:
        load_config(config)
    except ConfigException as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=2) from None

    # The uvicorn worker is a fresh process that re-imports main.py and cannot
    # receive -c directly. Export it so create_app() reconstructs the same app
    # (otherwise the worker falls back to the zero-config default state_home).
    os.environ["PROGRESS_CONFIG"] = config

    uvicorn.run("progress.api.main:app", host=host, port=port, reload=reload)


__all__ = ["app"]
