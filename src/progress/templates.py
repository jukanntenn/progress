"""Centralized Jinja2 template rendering.

Provides a single :func:`render` entry point for the whole project. Template
directories are auto-discovered, the :class:`~jinja2.Environment` is cached, and
all custom filters/globals are registered in one place so every template has a
consistent rendering context.

Template discovery:
  - ``src/progress/templates``               (main catalog)
  - ``src/progress/contrib/*/templates``     (per-plugin catalogs, if any)
"""

from __future__ import annotations

from functools import partial
from html import escape
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .i18n import gettext as _

_PACKAGE_DIR = Path(__file__).parent


def _escape_html(text: Any) -> str:
    """Escape HTML metacharacters in text."""
    return escape(str(text))


def _basename(path: str) -> str:
    """Return the final path component (mirrors ``os.path.basename``)."""
    return Path(path).name


def _discover_template_dirs() -> list[Path]:
    """Discover template directories under the package and contrib plugins."""
    dirs: list[Path] = []

    main_templates = _PACKAGE_DIR / "templates"
    if main_templates.is_dir():
        dirs.append(main_templates)

    contrib_dir = _PACKAGE_DIR / "contrib"
    if contrib_dir.is_dir():
        for item in sorted(contrib_dir.iterdir()):
            if item.is_dir():
                contrib_templates = item / "templates"
                if contrib_templates.is_dir():
                    dirs.append(contrib_templates)

    return dirs


def _build_environment() -> Environment:
    """Build a configured Jinja2 :class:`Environment` with shared defaults."""
    lookup = [str(p) for p in _discover_template_dirs()]
    if not lookup:
        raise RuntimeError("No template directories found under the package.")

    env = Environment(
        loader=FileSystemLoader(lookup),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    env.globals["_"] = _  # ty: ignore[invalid-assignment]  # Jinja2 globals accepts arbitrary callables; ty infers a narrow union from default globals
    env.filters["escape_html"] = _escape_html
    env.filters["basename"] = _basename

    return env


_environment: Environment | None = None


def get_environment() -> Environment:
    """Return the cached shared :class:`~jinja2.Environment` (lazy singleton)."""
    global _environment
    if _environment is None:
        _environment = _build_environment()
    return _environment


def register_filter(name: str, func: Any) -> None:
    """Register a custom Jinja2 filter on the shared environment."""
    get_environment().filters[name] = func


def register_global(name: str, value: Any) -> None:
    """Register a custom Jinja2 global on the shared environment."""
    get_environment().globals[name] = value


def render(name: str, **context: Any) -> str:
    """Render a template by filename with the given context.

    Args:
        name: Template filename (e.g. ``"repository_report.j2"``).
        **context: Variables passed to the template.

    Returns:
        Rendered template string.
    """
    template = get_environment().get_template(name)
    return template.render(**context)


def render_string(source: str, **context: Any) -> str:
    """Render an inline template string with the given context.

    Args:
        source: Template source string.
        **context: Variables passed to the template.

    Returns:
        Rendered template string.
    """
    template = get_environment().from_string(source)
    return template.render(**context)


render_template = partial(render)
