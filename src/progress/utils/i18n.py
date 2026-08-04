"""i18n via stdlib ``gettext`` + ``ContextVar`` (spec 11).

Locale is stored per-async-context in a ``ContextVar`` so concurrent requests
in the API can each carry their own locale without a thread-local.

Locale codes are BCP-47 lowercase (``zh-hans``); file paths under
``<pkg>/locales/<code>/LC_MESSAGES/progress.mo``.

We provide the full stdlib gettext contract: ``gettext``, ``ngettext``,
``pgettext``, ``npgettext`` (signatures mirror Python's ``gettext`` module
and Django's ``trans_real``). ``gettext_lazy`` is still omitted — every
``_()`` call sits inside a function body where the active locale is set, so
lazy evaluation is unnecessary. ``ngettext`` was previously removed as "dead
code" but is required for correct pluralization in templates (e.g.
"1 commit" vs "2 commits").
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import gettext as _gettext
from pathlib import Path

DEFAULT_LOCALE: str = "en"
DOMAIN: str = "progress"

#: Context separator used by stdlib ``pgettext``/``npgettext`` to pack the
#: msgctxt and msgid into one catalog key (mirrors Django's CONTEXT_SEPARATOR).
_CONTEXT_SEPARATOR = "\x04"

_current_locale: ContextVar[str] = ContextVar("progress_locale", default=DEFAULT_LOCALE)
_translation_cache: dict[tuple[str, Path], _gettext.NullTranslation | _gettext.GNUTranslations] = {}  # ty:ignore[unresolved-attribute]


def get_locale() -> str:
    """Return the locale active in the current async context."""
    return _current_locale.get()


def set_locale(locale: str) -> None:
    """Set the locale for the current async context."""
    _current_locale.set(locale.lower() if locale else DEFAULT_LOCALE)


def _locales_root() -> Path:
    return Path(__file__).resolve().parent.parent / "locales"


def _load_translation(
    locale: str, locales_root: Path | None = None
) -> _gettext.NullTranslation | _gettext.GNUTranslations:  # ty:ignore[unresolved-attribute]
    """Load the GNU translation for ``locale``; fall back to NullTranslation.

    Per spec 11 we distinguish "file missing" (normal fallback) from
    "parse error" (raise). A missing ``.mo`` is the common case for ``en`` and
    any locale that hasn't been compiled yet.
    """
    root = (locales_root or _locales_root()) / locale / "LC_MESSAGES"
    mo_path = root / f"{DOMAIN}.mo"
    if not mo_path.exists():
        return _gettext.NullTranslations()
    try:
        with mo_path.open("rb") as fp:
            return _gettext.GNUTranslations(fp)
    except (OSError, ValueError) as e:
        raise RuntimeError(f"failed to parse {mo_path}: {e}") from e


def _get_translation(locale: str) -> _gettext.NullTranslation | _gettext.GNUTranslations:  # ty:ignore[unresolved-attribute]
    """Return a cached translation for ``locale``.

    Searches the central locales directory first, then any integration-specific
    directories registered via :func:`install_locale_dir`.
    """
    key = (locale, _locales_root())
    if key not in _translation_cache:
        _translation_cache[key] = _load_translation(locale)
    return _translation_cache[key]


def _collect_all_translations(locale: str) -> _gettext.NullTranslations:
    """Merge translations from central + all installed integration locale dirs.

    Per spec 11, locales are distributed across packages.  This function
    chains them so ``gettext()`` searches all registered catalogs.
    """
    translations = _get_translation(locale)
    # Chain integration-specific translations
    for (cached_locale, cached_root), cached_trans in _translation_cache.items():
        if cached_locale == locale and cached_root != _locales_root() and hasattr(translations, "add_fallback"):
            translations.add_fallback(cached_trans)
    return translations


def gettext(message: str) -> str:
    """Translate ``message`` using the active locale's catalog.

    Searches central + all installed integration locale directories.
    """
    return _collect_all_translations(get_locale()).gettext(message)


def ngettext(singular: str, plural: str, number: int) -> str:
    """Translate ``singular``/``plural`` based on ``number`` (active locale).

    Mirrors ``gettext.ngettext``: at runtime the active locale's plural form
    selects the correct form. For ``nplurals=1`` locales (e.g. ``zh-hans``)
    the singular is always used.
    """
    return _collect_all_translations(get_locale()).ngettext(singular, plural, number)


def pgettext(context: str, message: str) -> str:
    """Translate ``message`` disambiguated by ``context`` (msgctxt).

    Mirrors Django's ``pgettext``: on a missing contextual translation we fall
    back to the plain message rather than leaking the ``\\x04`` separator that
    stdlib ``pgettext`` leaves in the result.
    """
    translated = _collect_all_translations(get_locale()).pgettext(context, message)
    if _CONTEXT_SEPARATOR in translated:
        return message
    return translated


def npgettext(context: str, singular: str, plural: str, number: int) -> str:
    """Context-aware plural translation (mirrors Django's ``npgettext``).

    Falls back to plain :func:`ngettext` when no contextual translation exists
    (the ``\\x04`` separator survives in the stdlib result in that case).
    """
    sep = _CONTEXT_SEPARATOR
    msgid = sep.join((context, singular))
    msgid_plural = sep.join((context, plural))
    translated = _collect_all_translations(get_locale()).ngettext(msgid, msgid_plural, number)
    if sep in translated:
        return ngettext(singular, plural, number)
    return translated


_ = gettext


@contextmanager
def override(locale: str) -> Iterator[None]:
    """Temporarily override the active locale (testing / explicit switching)."""
    token = _current_locale.set(locale.lower() if locale else DEFAULT_LOCALE)
    try:
        yield
    finally:
        _current_locale.reset(token)


def install_locale_dir(locales_dir: Path, locale: str | None = None) -> None:
    """Load a translation from a non-default ``locales_dir`` (e.g. integration's own).

    Useful for integration packages that ship their own ``locales/`` tree.
    """
    target = (locale or get_locale()).lower()
    key = (target, locales_dir.resolve())
    if key not in _translation_cache:
        _translation_cache[key] = _load_translation(target, locales_dir)


def negotiate_locale(accept_language: str) -> str:
    """Pick the best supported locale from an HTTP ``Accept-Language`` header.

    Supports the common ``zh-Hans`` style header value; everything is lowercased
    per spec 11.
    """
    if not accept_language:
        return DEFAULT_LOCALE
    candidates: list[tuple[float, str]] = []
    for raw_part in accept_language.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ";" in part:
            tag, q = part.split(";", 1)
            try:
                weight = float(q.strip().removeprefix("q="))
            except ValueError:
                weight = 1.0
        else:
            tag, weight = part, 1.0
        candidates.append((weight, tag.lower()))
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _, tag in candidates:
        if _locales_root().joinpath(tag).is_dir():
            return tag
        if "-" in tag:
            base = tag.split("-", 1)[0]
            if _locales_root().joinpath(base).is_dir():
                return base
    return DEFAULT_LOCALE


__all__ = [
    "DEFAULT_LOCALE",
    "DOMAIN",
    "_",
    "get_locale",
    "gettext",
    "install_locale_dir",
    "negotiate_locale",
    "ngettext",
    "npgettext",
    "override",
    "pgettext",
    "set_locale",
]
