"""Typer app + CLI command definitions (spec 05).

This is the CLI entry module: it owns the ``app`` Typer instance and the
``run`` / ``serve`` / ``users`` command registrations, plus the heavy imports
(``cli.core`` / ``config.loader`` / ``cli.users``) those commands need. It is
the only place these heavy modules are pulled in at module top level.

``progress.cli.__init__`` is intentionally minimal (a docstring only) so that
importing any ``progress.cli.*`` sub-module from the API path — notably
``config.root -> cli.notifications.config`` — does not eagerly drag in
``cli.core -> runtime -> config.loader``, which would form a circular
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

app = typer.Typer(invoke_without_command=True, help="Progress: GitHub multi-repo project tracking tool.")

app.add_typer(users_app, name="users")


@app.callback()
def _main(
    ctx: typer.Context,
    dump_config: bool = typer.Option(
        False, "--dump-config", help="Print the effective composition tree (expressions unevaluated) and exit."
    ),
    profile: str = typer.Option("run", "--profile", help="Profile to compose for --dump-config."),
    config: str = typer.Option("config.toml", "--config", help="Path to the Ansible-class config file."),
) -> None:
    """Global options."""
    if dump_config:
        from progress.cli.core import make_run_base_entries  # noqa: PLC0415
        from progress.kernel.patches import dump_rows  # noqa: PLC0415
        from progress.runtime.composition import effective_rows  # noqa: PLC0415

        try:
            cfg = load_config(config)
        except ConfigException:
            cfg = None
        rows = effective_rows(make_run_base_entries(cfg, config_path=config), profile=profile, cfg=cfg)
        typer.echo(dump_rows(rows))
        raise typer.Exit
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(2)


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
def inspect(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
    profile: str = typer.Option("run", "--profile", help="Profile to compose and activate."),
) -> None:
    """Boot the composition tree, print fiber states, fail loud on stuck rows."""
    import asyncio  # noqa: PLC0415

    cfg = load_config(config)
    from progress.cli.core import make_run_base_entries  # noqa: PLC0415
    from progress.kernel import boot  # noqa: PLC0415
    from progress.runtime.composition import effective_rows, rows_to_entries  # noqa: PLC0415
    from progress.runtime.plugin_install import ensure_plugin_path  # noqa: PLC0415

    ensure_plugin_path(cfg.state_home)
    rows = effective_rows(make_run_base_entries(cfg, config_path=config), profile=profile, cfg=cfg)
    entries = rows_to_entries(rows)

    async def _inspect() -> int:
        try:
            async with boot(entries) as ctx:
                for fiber in ctx.root_fiber.walk():
                    if fiber.name != "root":
                        typer.echo(fiber.diagnostics())
                return 0
        except Exception as e:
            typer.echo(str(e), err=True)
            return 2

    raise typer.Exit(code=asyncio.run(_inspect()))


plugin_app = typer.Typer(help="Third-party plugin management (install, list, remove).")


@plugin_app.command("add")
def plugin_add(
    requirement: str = typer.Argument(..., help="Package path or requirement to install."),
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """Install a plugin into <state_home>/plugins via uv (--no-deps)."""
    cfg = load_config(config)
    from progress.runtime.plugin_install import install_plugin  # noqa: PLC0415

    try:
        output = install_plugin(cfg.state_home, requirement)
        if output:
            typer.echo(output)
        typer.echo(f"installed {requirement}; activation is a recompose (SIGHUP or /config/reload)")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None


@plugin_app.command("list")
def plugin_list(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """List installed plugin distributions."""
    cfg = load_config(config)
    from progress.runtime.plugin_install import list_plugins  # noqa: PLC0415

    plugins = list_plugins(cfg.state_home)
    if not plugins:
        typer.echo("(no plugins installed)")
        return
    for plugin in plugins:
        typer.echo(f"{plugin['name']:<30} {plugin['version']:<12} {plugin['entry_points']}")


@plugin_app.command("remove")
def plugin_remove(
    name: str = typer.Argument(..., help="Distribution name to remove."),
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the config file."),
) -> None:
    """Remove an installed plugin distribution."""
    cfg = load_config(config)
    from progress.runtime.plugin_install import remove_plugin  # noqa: PLC0415

    if not remove_plugin(cfg.state_home, name):
        typer.echo(f"Error: no installed plugin named {name!r}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"removed {name}")


app.add_typer(plugin_app, name="plugin")


@app.command()
def serve(
    config: str = typer.Option("config.toml", "--config", "-c", help="Path to the Ansible-class config file."),
    host: str = typer.Option("0.0.0.0", "--host"),
    port: int = typer.Option(8000, "--port"),
    reload: bool = typer.Option(False, "--reload"),
    dev_plugin_watch: bool = typer.Option(
        False, "--dev-plugin-watch", help="L2 dev mode: hot-replace third-party plugin modules (default off)."
    ),
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
    os.environ["PROGRESS_DEV_PLUGIN_WATCH"] = "1" if dev_plugin_watch else ""

    uvicorn.run("progress.api.main:app", host=host, port=port, reload=reload)


__all__ = ["app"]
