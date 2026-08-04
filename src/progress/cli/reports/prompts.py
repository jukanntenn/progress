"""Jinja2 prompt template loader for AI analysis (spec 08).

Prompts are co-located with their owning package per spec 06 (self-contained
integrations):

- ``cli/reports/prompts/`` — prompts owned by the reports pipeline itself
  (e.g. ``title_summary_prompt.j2`` rendered at
  :func:`progress.cli.reports.pipeline.generate_title_summary`).
- ``integrations/<name>/prompts/`` — prompts owned by each integration, for
  when that integration wires in AI analysis of its own content.

The loader discovers integration ``prompts/`` directories via the registry
(mirroring :func:`progress.cli.reports.pipeline._collect_integration_template_dirs`)
and feeds them all to one Jinja2 ``ChoiceLoader`` so a caller rendering
``"proposal_new_prompt.j2"`` finds it inside the ``proposal`` integration
without knowing where it lives.

Prompt content is rendered to a string and then fed to the Pydantic AI
agent's ``run()`` call (not via stdin like the legacy CLI shell-out).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from progress.integrations.registry import discover_integrations
from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.templating import create_environment

_REPORTS_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def _collect_integration_prompt_dirs() -> list[Path]:
    """Collect ``prompts/`` directories from all registered integrations.

    Per spec 06, each integration is self-contained with its own ``prompts/``
    directory. This function discovers them via the registry so adding a new
    integration (or wiring AI analysis into an existing one) requires zero
    changes here.
    """

    dirs: list[Path] = [_REPORTS_PROMPTS_DIR]
    for name in discover_integrations():
        integration_prompts = Path(__file__).resolve().parents[2] / "integrations" / name / "prompts"
        if integration_prompts.is_dir():
            dirs.append(integration_prompts)
    return dirs


_env: Any = None


def _get_env() -> Any:
    """Lazily build the Jinja2 environment on first render.

    Building at import time creates an import-order hazard: ``prompts.py`` is
    imported by ``pipeline.py`` which is imported by ``reports/__init__.py``,
    and discovering integration ``prompts/`` dirs at that point can trigger
    integration imports before they are ready (the registry would then cache
    an empty result). Deferring to first render — which only happens inside a
    running lifespan — sidesteps the whole ordering problem.
    """
    global _env
    if _env is None:
        env = create_environment(_collect_integration_prompt_dirs())
        env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # ty:ignore[no-matching-overload]
        _env = env
    return _env


def render_prompt(template_name: str, **context: Any) -> str:
    """Render ``<template_name>`` with ``context`` variables.

    ``template_name`` is the bare filename (e.g. ``"title_summary_prompt.j2"``).
    The ``_()`` i18n function is registered as a global so templates can use
    ``{{ _("...") }}``.
    """
    env = _get_env()
    template = env.get_template(template_name)
    template.globals["_"] = _
    return template.render(**context)


__all__ = ["render_prompt"]
