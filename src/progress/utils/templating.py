"""Jinja2 environment factory with safe autoescape (spec 09).

The Jinja2 environment is the shared rendering engine. Templates are co-located
with their owning packages per spec 06 (self-contained integrations):

* ``cli/reports/templates/reports/`` — aggregated report templates (reports-owned)
* ``integrations/<name>/templates/`` — each integration's own section templates
  (``<name>_report.j2``), plus its notification templates under
  ``integrations/<name>/templates/notifications/<event_kind>/``
* ``cli/notifications/templates/`` — notification templates owned by the
  notification system itself (the core ``report`` event kind)
* ``cli/reports/prompts/`` + ``integrations/<name>/prompts/`` — AI prompt
  templates, co-located with their owning package

Each concern (reports, notifications, prompts) builds its own
:func:`create_environment` with a registry-discovered ``ChoiceLoader`` over the
relevant co-located directories.

Autoescape is enabled for ``html``, ``htm``, ``xml`` and ``j2`` extensions per
the spec; ``Markup`` (``|safe``) is only applied **after** nh3 sanitize.

One exception: **report** templates (``pipeline._get_env``) are markdown-
producing — they emit literal HTML (``<details>``, ``<small>``) and trusted AI
output that is later sanitized by nh3 (backend) and rehype-sanitize (frontend,
spec 09/13). Autoescape there would mangle that HTML into entities, so report
templates build their environment with ``autoescape=False`` and escape
untrusted data (commit messages, release notes) explicitly with ``|e``. HTML
notification templates keep autoescape on because their whole output is HTML
where every interpolation must be escaped.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, Undefined, select_autoescape

AUTOESCAPE_EXTENSIONS = ("html", "htm", "xml", "j2")


def create_environment(
    search_paths: Iterable[str | Path],
    *,
    enable_async: bool = False,
    autoescape: bool = True,
    undefined: type[Undefined] = Undefined,
) -> Environment:
    """Build a Jinja2 ``Environment`` rooted at ``search_paths``.

    ``search_paths`` is tried in order via ``ChoiceLoader`` of
    ``FileSystemLoader`` entries; templates loaded from any path share the
    same autoescape policy.

    ``autoescape`` defaults to ``True`` (HTML notification templates). Report
    templates pass ``False`` because they produce markdown that is sanitized
    downstream — see the module docstring.

    ``undefined`` defaults to the silent ``Undefined``; report templates pass
    ``StrictUndefined`` so a missing payload key raises at render time and is
    caught by the section-level graceful-degradation handler instead of
    silently rendering an empty string.
    """
    paths = [str(p) for p in search_paths]
    escape_policy = (
        select_autoescape(enabled_extensions=AUTOESCAPE_EXTENSIONS, default_for_string=True) if autoescape else False
    )
    # escape_policy is select_autoescape(...) when autoescape=True (the default,
    # used by HTML notification templates); it is only False for markdown-producing
    # report templates whose output is sanitized downstream by nh3 (backend) +
    # rehype-sanitize (frontend). See the module docstring.
    env = Environment(
        loader=ChoiceLoader([FileSystemLoader(p) for p in paths]) if len(paths) > 1 else FileSystemLoader(paths),
        autoescape=escape_policy,  # nosec B701
        undefined=undefined,
        trim_blocks=True,
        lstrip_blocks=True,
        enable_async=enable_async,
    )
    env.filters["basename"] = _basename
    return env


def _basename(path: str) -> str:
    """Return the final component of a path (filters in templates)."""
    if not path:
        return ""
    return path.rsplit("/", 1)[-1]


__all__ = ["AUTOESCAPE_EXTENSIONS", "create_environment"]
