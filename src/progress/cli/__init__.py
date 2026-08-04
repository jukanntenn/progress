"""CLI package (spec 05).

Intentionally minimal: the Typer ``app`` and command definitions live in
``progress.cli.main``. Keeping this module import-free prevents the circular
import described in ``cli/main.py``'s docstring — the ``progress.cli`` package
is reached from the API import path via ``config.root ->
cli.notifications.config``, and any top-level import here of ``cli.core`` /
``cli.users`` would re-enter ``config.loader`` mid-initialization.
"""
