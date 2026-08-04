"""Rich terminal card renderer for the console channel.

This is the console counterpart of the Feishu ``_feishu_v2.j2`` macro library
and the email ``_email.j2`` macro library: it renders the same structured
notification (same per-kind data, same palette, same layout) as a colored
``rich`` card on stdout instead of a JSON card / HTML email.

Why the rendering lives in Python (not a Jinja2 template): ``rich`` components
(``Panel``, ``Table``, ``Text``) are Python objects assembled imperatively, and
Jinja2 templates emit strings. Building rich renderables from a template would
mean embedding Python literals in the template and ``eval``-ing them, which is
fragile. The per-kind structure is a thin dispatch (``render_console_card``)
that consumes ``event.data`` — the exact same fields the templates consume — so
there is no second data model to keep in sync.

Palette is kept in lock-step with ``_feishu_v2.j2`` header themes and
``_email.j2`` ACCENT/BG_FOR_COLOR maps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from progress.utils.i18n import gettext as _

if TYPE_CHECKING:
    from progress.cli.notifications.base import ChannelPayload
    from progress.cli.notifications.events import NotificationEvent

_ACCENT = {
    "red": "#F53F3F",
    "green": "#00B42A",
    "blue": "#3370FF",
    "indigo": "#4080FF",
    "wathet": "#0091FF",
    "turquoise": "#14C9C9",
}
_BADGE_FG = {
    "green": "#00B42A",
    "red": "#F53F3F",
    "blue": "#3370FF",
    "orange": "#FF7D00",
    "purple": "#722ED1",
    "turquoise": "#14C9C9",
    "indigo": "#4080FF",
    "grey": "#86909C",
}
_BADGE_BG = {
    "green": "#E8FFEA",
    "red": "#FFECE8",
    "blue": "#E8F3FF",
    "orange": "#FFF7E8",
    "purple": "#F5E8FF",
    "turquoise": "#E8FFFB",
    "indigo": "#E8F3FF",
    "grey": "#F2F3F5",
}


def _badge(text: str, color: str = "grey") -> Text:
    """A colored pill badge: tinted background + foreground color text."""
    fg = _BADGE_FG.get(color, "#86909C")
    bg = _BADGE_BG.get(color, "#F2F3F5")
    return Text(f" {text} ", style=f"{fg} on {bg}", end="")


def _heading(text: str) -> Text:
    return Text(text, style="bold #1D2129")


def _divider() -> Text:
    return Text("─" * 54, style="#E5E6EB")


def _stat_table(stats: list[dict[str, Any]]) -> Table:
    """A 3-tile stats row, mirroring the Feishu/email stats grid."""
    table = Table.grid(expand=True, padding=(0, 1))
    for _col in stats:
        table.add_column(ratio=1)
    cells: list[RenderableType] = []
    for s in stats:
        vc = _BADGE_FG.get(s.get("value_color", ""), "#1D2129")
        bg = _BADGE_BG.get(s.get("bg", "grey"), "#F7F8FA")
        block = Table.grid(expand=True)
        block.add_column()
        block.add_row(
            Group(
                Text(str(s["label"]), style="dim #86909C", justify="center"),
                Text(str(s["value"]), style=f"bold {vc}", justify="center"),
            ),
            style=f"on {bg}",
        )
        cells.append(block)
    table.add_row(*cells)
    return table


def _panel(title: str, accent: str, badge_text: str, badge_color: str, body: RenderableType) -> Panel:
    """The shared card frame: accent border + title line with a header badge."""
    accent_hex = _ACCENT.get(accent, "#3370FF")
    header = Text()
    header.append_text(Text(" " + title + " ", style=f"bold white on {accent_hex}"))
    if badge_text:
        header.append("  ")
        header.append_text(_badge(badge_text, badge_color))
    return Panel(
        body,
        title=header,
        title_align="left",
        border_style=accent_hex,
        padding=(1, 1),
        expand=False,
        width=58,
    )


def _status_line(name: str, url: str, status: str) -> Text:
    """A repo line with a clickable link and a colored status badge."""
    line = Text()
    line.append(" • ", style="dim")
    if url:
        line.append(name, style=f"link {url}")
    else:
        line.append(name, style="bold")
    color_map = {"success": "green", "failed": "red", "skipped": "grey"}
    label_map = {"success": _("SUCCESS"), "failed": _("FAILED"), "skipped": _("SKIPPED")}
    line.append("  ")
    line.append_text(_badge(label_map.get(status, status.upper()), color_map.get(status, "grey")))
    return line


def _cta(url: str, label: str) -> Text:
    """A CTA line: a clickable link styled like a primary button."""
    return Text.assemble(
        ("➜ ", "bold"),
        (label, f"bold link {url}"),
    )


def _render_repo_update(ev: NotificationEvent) -> RenderableType:
    data = ev.data
    repos: dict[str, str] = data.get("repo_statuses") or {}
    urls: dict[str, str] = data.get("repo_urls") or {}
    success_repos = [n for n, s in repos.items() if s == "success"]
    failed_repos = [n for n, s in repos.items() if s == "failed"]
    skipped_repos = [n for n, s in repos.items() if s not in ("success", "failed")]
    has_failure = bool(failed_repos)
    accent = "red" if has_failure else "green"
    badge_text = f"{_('FAILED')} {len(failed_repos)}" if has_failure else f"{_('SUCCESS')} {len(success_repos)}"
    stats = [
        {"label": _("Total Repositories"), "value": len(repos), "bg": "grey", "value_color": ""},
        {"label": _("Total Commits"), "value": data.get("total_commits", 0), "bg": "grey", "value_color": ""},
    ]
    if has_failure:
        stats.append({"label": _("Failed"), "value": len(failed_repos), "bg": "red", "value_color": "red"})
    else:
        stats.append({"label": _("Success Rate"), "value": "100%", "bg": "green", "value_color": "green"})

    body_parts: list[RenderableType] = []
    if ev.summary:
        body_parts.append(Text(f"📝 {_('Overview')}", style="bold #1D2129"))
        body_parts.append(Text(ev.summary, style="#4E5969"))
        body_parts.append(_divider())
    body_parts.append(_stat_table(stats))
    body_parts.append(_divider())
    if has_failure:
        body_parts.append(_heading(f"⚠ {_('Failed Repositories')} ({len(failed_repos)})"))
        body_parts.extend(_status_line(name, urls.get(name, ""), "failed") for name in failed_repos)
    else:
        body_parts.append(_heading(f"📦 {_('Successful Repositories')} ({len(success_repos)})"))
        body_parts.extend(_status_line(name, urls.get(name, ""), "success") for name in success_repos[:5])
        rest = success_repos[5:]
        if rest:
            body_parts.append(Text(f"▸ {_('Expand remaining')} {len(rest)} {_('repos')}", style="dim italic"))
    if skipped_repos:
        body_parts.append(Text(f"▸ {_('Skipped Repositories')} ({len(skipped_repos)})", style="dim italic"))
        body_parts.extend(_status_line(name, urls.get(name, ""), "skipped") for name in skipped_repos)
    if ev.markpost_url:
        body_parts.append(_divider())
        body_parts.append(_cta(ev.markpost_url, _("View Detailed Report")))
    return _panel(ev.title, accent, badge_text, accent, Group(*body_parts))


def _render_proposal(ev: NotificationEvent) -> RenderableType:
    data = ev.data
    proposals: list[dict[str, str]] = data.get("proposals") or []
    visible = proposals[:5]
    rest = proposals[5:]
    status_color = {
        "Final": "green",
        "Review": "orange",
        "Draft": "grey",
        "Idea": "grey",
        "Withdrawn": "red",
        "Rejected": "red",
        "Stagnant": "grey",
        "Living": "blue",
    }
    kind_color = {"EIP": "blue", "ERC": "purple", "PEP": "turquoise", "RFC": "indigo", "DEP": "orange"}
    table = Table(expand=True, width=54, show_edge=False, pad_edge=False, padding=(0, 1))
    table.add_column(_("Proposal"), ratio=55, overflow="fold")
    table.add_column(_("Type"), ratio=15)
    table.add_column(_("Status"), ratio=30, overflow="fold")
    for p in visible:
        status_text = (
            f"{p.get('old_status', '')} → {p.get('new_status', '')}".strip(" →")
            if p.get("old_status")
            else f"{p.get('new_status', '')} ({_('new')})"
        )
        sc = status_color.get(p.get("new_status", ""), "grey")
        kc = kind_color.get(p.get("kind", ""), "grey")
        prop_text = Text(f"#{p.get('number', '')} {p.get('title') or p.get('file_name', '')}")
        if p.get("file_url"):
            prop_text.stylize(f"link {p['file_url']}")
        type_cell = _badge(p.get("kind", ""), kc)
        status_cell = _badge(status_text, sc)
        table.add_row(prop_text, type_cell, status_cell)
    body_parts: list[RenderableType] = [_heading(f"📄 {_('Proposal List')}"), table]
    if rest:
        body_parts.append(Text(f"▸ {_('Expand remaining')} {len(rest)} {_('proposals')}", style="dim italic"))
        body_parts.append(
            Text(
                "  " + "  ".join(f"#{p.get('number', '')} {p.get('title') or p.get('file_name', '')}" for p in rest),
                style="#4E5969",
            )
        )
    if ev.markpost_url:
        body_parts.append(_divider())
        body_parts.append(_cta(ev.markpost_url, _("View Proposal Details")))
    return _panel(ev.title, "blue", f"NEW {len(proposals)}", "blue", Group(*body_parts))


def _render_changelog(ev: NotificationEvent) -> RenderableType:
    data = ev.data
    entries: list[dict[str, Any]] = data.get("entries") or []
    visible = entries[:5]
    rest = entries[5:]
    level_color = {"MAJOR": "red", "MINOR": "blue", "PATCH": "grey"}
    body_parts: list[RenderableType] = [_heading(f"📦 {_('Version List')}")]
    for e in visible:
        lc = level_color.get(e.get("level", ""), "grey")
        line = Text()
        line.append(f" • {e.get('name', '')} ", style="bold")
        line.append(e.get("version", ""), style="on #F2F3F5 #4E5969")
        if e.get("level"):
            line.append("  ")
            line.append_text(_badge(f"{e['level']} ⬆", lc))
        if e.get("url"):
            line.append("    ")
            line.append_text(Text(f"{_('Release Note')}", style=f"link {e['url']}"))
        body_parts.append(line)
    if rest:
        body_parts.append(Text(f"▸ {_('Expand remaining')} {len(rest)} {_('versions')}", style="dim italic"))
        body_parts.extend(Text(f"    {e.get('name', '')} {e.get('version', '')}", style="#4E5969") for e in rest)
    if ev.markpost_url:
        body_parts.append(_divider())
        body_parts.append(_cta(ev.markpost_url, _("View Full Changelog")))
    return _panel(ev.title, "indigo", f"RELEASE {len(entries)}", "indigo", Group(*body_parts))


def _render_feed(ev: NotificationEvent) -> RenderableType:
    data = ev.data
    feeds: list[dict[str, Any]] = data.get("feeds") or []
    total = sum(f.get("entry_count", 0) for f in feeds) or data.get("entry_count", 0)
    body_parts: list[RenderableType] = [_heading(f"📡 {_('Feed Sources')}")]
    if feeds:
        batch = feeds[:3]
        table = Table.grid(expand=True, padding=(0, 1))
        for _col in batch:
            table.add_column(ratio=1)
        cells: list[RenderableType] = []
        for f in batch:
            block = Table.grid(expand=True)
            block.add_column()
            block.add_row(
                Group(
                    Text(f"📡 {f.get('title', '')}", style="bold #1D2129", justify="center"),
                    Text(str(f.get("entry_count", 0)), style="bold #0091FF", justify="center"),
                    Text(_("new articles"), style="dim #86909C", justify="center"),
                ),
                style="on #E8F3FF",
            )
            cells.append(block)
        table.add_row(*cells)
        body_parts.append(table)
        rest = feeds[3:]
        if rest:
            body_parts.append(
                Text(
                    "  " + "  ".join(f"{f.get('title', '')} ({f.get('entry_count', 0)})" for f in rest), style="#4E5969"
                )
            )
    if ev.markpost_url:
        body_parts.append(_divider())
        body_parts.append(_cta(ev.markpost_url, _("View Full Digest")))
    run_at = data.get("run_at")
    if run_at:
        body_parts.append(Text(f"⏱ {_('Report tool: Progress @')} {run_at}", style="dim #86909C"))
    return _panel(
        ev.title,
        "wathet",
        f"{total} {_('new')}",
        "wathet",
        Group(*body_parts),
    )


def _render_discovered_repo(ev: NotificationEvent) -> RenderableType:
    data = ev.data
    repos: list[dict[str, str]] = data.get("repos") or []
    visible = repos[:5]
    rest = repos[5:]
    body_parts: list[RenderableType] = [_heading(f"📦 {_('Newly Discovered Repositories')}")]
    for repo in visible:
        line = Text(" • ")
        line.append(f"📦 {repo.get('name', '')}", style="bold")
        if repo.get("url"):
            line.append("    ")
            line.append_text(Text(f"{_('View')}", style=f"link {repo['url']}"))
        body_parts.append(line)
    if rest:
        body_parts.append(Text(f"▸ {_('Expand remaining')} {len(rest)} {_('repos')}", style="dim italic"))
        body_parts.append(Text("  " + "  ".join(r.get("name", "") for r in rest), style="#4E5969"))
    body_parts.append(Text(f"💡 {_('New repos can be added under integrations.repo in config.toml')}", style="#3370FF"))
    if ev.markpost_url:
        body_parts.append(_divider())
        body_parts.append(_cta(ev.markpost_url, _("View Discovery Details")))
    return _panel(ev.title, "turquoise", f"NEW {len(repos)}", "turquoise", Group(*body_parts))


def _render_test(ev: NotificationEvent) -> RenderableType:  # pragma: no cover - trivial
    body_parts: list[RenderableType] = [
        Text(f"✅ {_('Notification channel configured correctly!')}", style="bold #00B42A", justify="center"),
        Text(
            _("This is a test notification. If you received this, the notification channel is configured correctly."),
            style="dim #86909C",
            justify="center",
        ),
    ]
    return _panel(ev.title, "green", "TEST", "green", Group(*body_parts))


_RENDERERS = {
    "repo_update": _render_repo_update,
    "proposal": _render_proposal,
    "changelog": _render_changelog,
    "feed": _render_feed,
    "discovered_repo": _render_discovered_repo,
    "test": _render_test,
}


def render_console_card(payload: ChannelPayload) -> RenderableType | None:
    """Render a structured rich card for ``payload``'s originating event.

    Returns ``None`` when no structured renderer matches (unknown kind, or the
    payload carries no event in its metadata) — the caller then falls back to
    printing ``payload.body`` (the plain-text template output) instead.

    Never raises: a console rendering failure must never break notification
    delivery (the structlog summary line has already captured the content).
    """
    event = payload.metadata.get("event")
    if event is None:
        return None
    kind = getattr(event, "kind", "")
    renderer = _RENDERERS.get(kind)
    if renderer is None:
        return None
    try:
        return renderer(event)
    except Exception:
        return None


__all__ = ["render_console_card"]
