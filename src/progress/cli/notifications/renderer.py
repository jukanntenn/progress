"""Jinja2-based event renderer (spec 10).

The renderer is a pure function: ``Event + ContentType -> ChannelPayload``.

Templates are co-located per spec 06 (self-contained integrations):

- ``cli/notifications/templates/{event_kind}/{content_type}.j2`` — templates
  owned by the notification system itself (the ``report`` kind, which is the
  aggregated report and not owned by any one integration).
- ``integrations/<name>/templates/notifications/{event_kind}/{content_type}.j2``
  — templates owned by each integration for its own event kinds (e.g. the
  ``proposal`` integration owns ``proposal/*``, the ``changelog`` integration
  owns ``changelog/*``, the ``repo`` integration owns ``discovered_repo/*``).

The renderer discovers each integration's ``templates/notifications/`` dir via
the registry (mirroring
:func:`progress.cli.reports.pipeline._collect_integration_template_dirs`) and
feeds them all to one Jinja2 ``ChoiceLoader``. Template lookup is
``{event_kind}/{content_type_suffix}.j2``.

This replaces the legacy N×M class matrix (ConsoleMessage × EmailMessage ×
FeishuMessage × proposal variants) with a declarative template matrix.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from progress.cli.notifications.base import ChannelPayload, ContentType
from progress.cli.notifications.events import (
    NotificationEvent,
    ReportEvent,
    TestNotificationEvent,
)
from progress.integrations.registry import discover_integrations
from progress.utils.i18n import gettext as _, ngettext, npgettext, pgettext
from progress.utils.templating import create_environment

_NOTIFICATIONS_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


def _collect_integration_notification_dirs() -> list[Path]:
    """Collect ``templates/notifications/`` dirs from all registered integrations.

    Per spec 06, each integration is self-contained. Event kinds that an
    integration owns (e.g. ``proposal``, ``changelog``, ``discovered_repo``)
    have their notification templates inside the integration's own
    ``templates/notifications/<kind>/`` directory. Discovery is registry-driven
    so adding a new integration requires zero changes here.
    """

    dirs: list[Path] = [_NOTIFICATIONS_TEMPLATES_DIR]
    for name in discover_integrations():
        integration_notifications = (
            Path(__file__).resolve().parents[2] / "integrations" / name / "templates" / "notifications"
        )
        if integration_notifications.is_dir():
            dirs.append(integration_notifications)
    return dirs


_env: Any = None


def _get_env() -> Any:
    """Lazily build the Jinja2 environment on first render.

    Building at import time creates an import-order hazard: ``renderer.py``
    is imported (transitively, via ``config.root`` → ``notifications.config`` →
    ``notifications.__init__``) before any integration has registered, so
    :func:`discover_integrations` would import the integration packages while
    the ``config``/``db`` modules they depend on are still initialising — the
    registry would then cache an empty result and integration notification
    templates would never be found. Deferring to first render (which only
    happens inside a running lifespan) sidesteps the whole ordering problem.
    """
    global _env
    if _env is None:
        env = create_environment(_collect_integration_notification_dirs())
        env.globals.update({"_": _, "ngettext": ngettext, "npgettext": npgettext, "pgettext": pgettext})  # ty:ignore[no-matching-overload]
        _env = env
    return _env


_CONTENT_TYPE_SUFFIX = {
    ContentType.HTML: "html",
    ContentType.PLAIN_TEXT: "plain_text",
    ContentType.CARD_JSON: "card_json",
}


class JinjaRenderer:
    """Render events into ``ChannelPayload`` via Jinja2 templates.

    Template lookup: ``{event_kind}/{content_type_suffix}.j2``. If a template
    is missing, the renderer falls back to a plain-text summary so the
    pipeline never silently drops a notification.

    The originating ``event`` is attached to ``metadata["event"]`` so the
    console channel can re-derive structured rich output from the same data
    the templates consumed (without it the channel only has the rendered
    plain-text body, which is too flat to reconstruct a rich card).
    """

    def render(self, event: Any, content_type: ContentType) -> ChannelPayload:
        kind = getattr(event, "kind", "report")
        suffix = _CONTENT_TYPE_SUFFIX.get(content_type, "plain_text")
        template_name = f"{kind}/{suffix}.j2"
        template_vars: dict[str, Any] = {"event": event}
        if isinstance(event, NotificationEvent):
            template_vars["title"] = event.title
            template_vars["summary"] = event.summary
            template_vars["markpost_url"] = event.markpost_url
            template_vars.update(event.data)
        try:
            template = _get_env().get_template(template_name)
            body = template.render(**template_vars)
        except Exception:
            body = _fallback_text(event)
        title = _derive_title(event)
        metadata: dict[str, Any] = {"event": event}
        if isinstance(event, NotificationEvent) and event.markpost_url:
            metadata["report_url"] = event.markpost_url
        elif isinstance(event, ReportEvent) and event.report_url:
            metadata["report_url"] = event.report_url
        return ChannelPayload(
            title=title,
            body=body,
            content_type=content_type,
            metadata=metadata,
        )


def _add_batch_indicator(title: str, event: NotificationEvent) -> str:
    """Append ``(N/M)`` to the title when a report spans multiple batches."""
    if event.total_batches and event.total_batches > 1:
        return f"{title} ({event.batch_index + 1}/{event.total_batches})"
    return title


def _derive_title(event: Any) -> str:
    if isinstance(event, TestNotificationEvent):
        return _("Test Notification")
    if isinstance(event, NotificationEvent):
        return _add_batch_indicator(event.title, event)
    if isinstance(event, ReportEvent):
        return event.title
    return getattr(event, "title", "Notification")


def _fallback_text(event: Any) -> str:
    if isinstance(event, TestNotificationEvent):
        return _("✅ Test Notification from Progress")
    if isinstance(event, NotificationEvent):
        lines = [event.title]
        if event.summary:
            lines.append(event.summary)
        if event.markpost_url:
            lines.append(event.markpost_url)
        return "\n".join(lines)
    if isinstance(event, ReportEvent):
        lines = [event.title, event.summary]
        for repo in event.repos:
            lines.append(f"  - {repo.name}: {repo.status}")
        return "\n".join(lines)
    return str(event)


__all__ = ["JinjaRenderer"]
