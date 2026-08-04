"""Single source of truth for notification status semantics (spec 10).

Every channel (email HTML, Feishu card JSON, console rich card) renders the
same status concepts — repo clone status, proposal lifecycle status, proposal
kind, changelog bump level. Before this module the status→color / status→label
/ status→icon mappings were duplicated across:

  * ``console_card.py`` (``color_map`` / ``label_map`` / ``status_color`` /
    ``kind_color`` / ``level_color`` locals)
  * ``templates/repo_update/card_json.j2`` (``badge_color`` dict)
  * ``templates/_feishu_v2.j2`` (``repo_line`` default ``color_map``)
  * ``integrations/proposal/.../{html,card_json}.j2`` (``status_color`` /
    ``kind_color`` dicts)
  * ``integrations/changelog/.../{html,card_json}.j2`` (``level_color`` dict)

Each copy was "kept in lock-step" only by comments — there was no compile-time
guarantee they agreed, which is exactly how a translation drift
(``"Successful Repositories"`` → ``"失败的仓库"``) could ship to production
without any test catching it. This module is the one place those mappings live;
all channels and templates read from it.

Design constraints:

* **No i18n at import time.** ``status_label`` resolves the label msgid through
  :func:`progress.utils.i18n.gettext` at *call* time so the active locale's
  catalog is honored (the locale is per-async-context; resolving it at module
  import would pin it to the default locale forever).
* **Palette names, not hex.** Colors are palette names (``green``/``red``/…)
  understood by every channel's own palette table (``_email.j2`` ACCENT /
  ``console_card._BADGE_FG`` / Feishu ``template``). This stays decoupled from
  any one channel's hex values.
* **Defensive lookup.** An unknown status key never raises (that would crash
  rendering and drop a notification); it falls back to ``grey`` + the raw key.
"""

from __future__ import annotations

from typing import Literal

from progress.utils.i18n import gettext as _

Category = Literal["repo_status", "proposal_status", "proposal_kind", "changelog_level"]

_DEFAULT_COLOR = "grey"

#: Per-status semantic triple: ``color`` is a palette name shared by every
#: channel's palette table; ``icon`` is a channel-agnostic glyph; ``label_key``
#: is the i18n msgid resolved by :func:`status_label`.
STATUS_SPEC: dict[str, dict[str, dict[str, str]]] = {
    "repo_status": {
        "success": {"color": "green", "icon": "✅", "label_key": "SUCCESS"},
        "failed": {"color": "red", "icon": "❌", "label_key": "FAILED"},
        "skipped": {"color": "grey", "icon": "➖", "label_key": "SKIPPED"},
    },
    "proposal_status": {
        "Final": {"color": "green", "icon": "✅", "label_key": "Final"},
        "Review": {"color": "orange", "icon": "🔍", "label_key": "Review"},
        "Draft": {"color": "grey", "icon": "✏️", "label_key": "Draft"},
        "Idea": {"color": "grey", "icon": "💡", "label_key": "Idea"},
        "Withdrawn": {"color": "red", "icon": "↩️", "label_key": "Withdrawn"},
        "Rejected": {"color": "red", "icon": "🚫", "label_key": "Rejected"},
        "Stagnant": {"color": "grey", "icon": "💤", "label_key": "Stagnant"},
        "Living": {"color": "blue", "icon": "🌱", "label_key": "Living"},
    },
    "proposal_kind": {
        "EIP": {"color": "blue", "icon": "📘", "label_key": "EIP"},
        "ERC": {"color": "purple", "icon": "📘", "label_key": "ERC"},
        "PEP": {"color": "turquoise", "icon": "📘", "label_key": "PEP"},
        "RFC": {"color": "indigo", "icon": "📘", "label_key": "RFC"},
        "DEP": {"color": "orange", "icon": "📘", "label_key": "DEP"},
    },
    "changelog_level": {
        "MAJOR": {"color": "red", "icon": "⬆️", "label_key": "MAJOR"},
        "MINOR": {"color": "blue", "icon": "⬆️", "label_key": "MINOR"},
        "PATCH": {"color": "grey", "icon": "⬆️", "label_key": "PATCH"},
    },
}


def _spec(category: str, key: str) -> dict[str, str]:
    """Return the status spec triple for ``category``/``key``; defensive.

    ``category`` is typed ``str`` (not the ``Category`` literal) on purpose: an
    unknown category must return the default triple rather than raise, which is
    the defensive contract that keeps rendering crash-proof.
    """
    return STATUS_SPEC.get(category, {}).get(key) or {
        "color": _DEFAULT_COLOR,
        "icon": "",
        "label_key": key,
    }


def status_color(category: str, key: str) -> str:
    """Palette name for ``key`` in ``category`` (e.g. ``"green"``)."""
    return _spec(category, key)["color"]


def status_icon(category: str, key: str) -> str:
    """Channel-agnostic glyph for ``key`` in ``category`` (e.g. ``"✅"``)."""
    return _spec(category, key)["icon"]


def status_label(category: str, key: str) -> str:
    """Localized label for ``key`` in ``category``.

    Resolved through :func:`progress.utils.i18n.gettext` at call time so the
    active locale's catalog is honored. For statuses whose canonical name is
    already a proper noun (``EIP`` / ``Final`` …) the msgid is the name itself
    and an absent translation simply returns the name unchanged, which is
    correct.
    """
    # Resolve the spec first, then translate. Splitting the subscript off the
    # ``_()`` call avoids Babel's regex extractor misreading the literal dict
    # key ``"label_key"`` inside ``_(...["label_key"])`` as the msgid.
    label_key = _spec(category, key)["label_key"]
    return _(label_key)


# Static msgid registry for Babel extraction. The label keys above are resolved
# through ``_()`` only inside ``status_label`` with a *variable* argument, so
# Babel's static extractor cannot see them (it only captures literal-argument
# ``_("…")`` calls). This tuple lists every translatable label_key as a literal
# ``_()`` call purely so ``pybabel extract`` keeps the msgids in the catalog;
# its value is unused at runtime. Without it the refactored templates (which
# call ``status_label("repo_status", "skipped")`` instead of ``_("SKIPPED")``)
# would silently lose their translations.
_TRANSLATABLE_LABELS = (
    _("SUCCESS"),
    _("FAILED"),
    _("SKIPPED"),
)


__all__ = [
    "STATUS_SPEC",
    "Category",
    "status_color",
    "status_icon",
    "status_label",
]
