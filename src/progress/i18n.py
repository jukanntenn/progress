"""Internationalization (i18n) support using gettext.

Public API (stable):
    - :func:`initialize`   -- set the active language at startup
    - :func:`gettext`      -- translate a message (aliased as ``_``)
    - :func:`ngettext`     -- translate a message with plural forms
    - :func:`gettext_lazy` -- lazy translation proxy resolving at use time
    - :func:`get_language` -- return the currently active language
    - :func:`override`     -- temporarily switch the active language

The active language is held in a module global; the per-language translation
catalog is cached in a process-wide dict keyed by language code. Translations
themselves are resolved lazily per thread so that :func:`override` (and future
per-request language selection) can swap catalogs without rebuilding the cache.
"""

from __future__ import annotations

import typing

import gettext as gettext_module
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

DOMAIN = "progress"
LOCALE_DIR = Path(__file__).parent / "locales"

# Process-wide cache of compiled catalogs, keyed by language code.
# ``None`` is a valid key representing the English/fallback (NullTranslations).
_translations: dict[str | None, gettext_module.NullTranslations] = {}

# Active language for the "global" scope (set by :func:`initialize`).
_ui_language: str = "en"

# Per-thread override stack. Each thread resolves its active language against
# the top of its own stack, falling back to ``_ui_language``.
_thread_local = threading.local()


def _thread_stack() -> list[str | None]:
    stack = getattr(_thread_local, "override_stack", None)
    if stack is None:
        stack = []
        _thread_local.override_stack = stack
    return stack


def initialize(ui_language: str = "en") -> None:
    """Initialize translation system with language configuration.

    This must be called once at application startup before using any
    translation functions. Subsequent calls update the active language and
    invalidate any per-thread override state.

    Args:
        ui_language: Language code for UI/reports/notifications.
    """
    global _ui_language

    _ui_language = ui_language
    # Drop any cached NullTranslations for a language that may now resolve
    # differently after the active language changed.
    _thread_local.__dict__.pop("override_stack", None)

    logger.info("Translation initialized: UI=%s", ui_language)


def get_language() -> str | None:
    """Return the currently active language code for the calling thread."""
    stack = _thread_stack()
    if stack:
        return stack[-1]
    return _ui_language


def _active_translation() -> gettext_module.NullTranslations:
    """Return the translation object for the calling thread's active language."""
    return _load_translation(get_language())


def _load_translation(
    language: str | None = None,
) -> gettext_module.NullTranslations:
    """Load (and cache) a gettext translation object with fallback.

    Args:
        language: Language code. ``None``/empty yields a no-op
            :class:`~gettext.NullTranslations` that returns the msgid verbatim.

    Returns:
        The cached translation object for the requested language.
    """
    cached = _translations.get(language)
    if cached is not None:
        return cached

    if not language:
        translation: gettext_module.NullTranslations = (
            gettext_module.NullTranslations()
        )
        _translations[None] = translation
        return translation

    try:
        translation = gettext_module.translation(
            domain=DOMAIN,
            localedir=str(LOCALE_DIR),
            languages=[language],
            fallback=True,
        )
        logger.info("Loaded translation for language: %s", language)
    except Exception as e:
        logger.warning(
            "Failed to load translation for %s: %s, using fallback", language, e
        )
        translation = gettext_module.NullTranslations()

    _translations[language] = translation
    return translation


def gettext(message: str) -> str:
    """Translate a UI message (reports, notifications, user interface).

    Args:
        message: Message to translate.

    Returns:
        Translated message.
    """
    return _active_translation().gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate a message with plural-form support.

    Args:
        singular: Singular form message.
        plural: Plural form message.
        count: Count driving plural-form selection.

    Returns:
        Translated message in the appropriate form.
    """
    return _active_translation().ngettext(singular, plural, count)


@contextmanager
def override(language: str | None) -> Iterator[None]:
    """Temporarily activate ``language`` for the calling thread.

    Restores the previous active language on exit. Usable as
    ``with override("zh-hans"): ...``. Passing ``None`` forces the fallback
    (untranslated) catalog.

    Args:
        language: Language code to activate, or ``None`` for fallback.
    """
    stack = _thread_stack()
    stack.append(language)
    try:
        yield
    finally:
        stack.pop()


class _LazyString:
    """Proxy that defers translation until it is coerced to a string.

    Modeled on Django's ``gettext_lazy``: the message and (optional) count are
    captured at definition time; the active language at *use* time determines
    the rendered string.
    """

    __slots__ = ("_func", "_args", "_kwargs")

    def __init__(self, func, args, kwargs):
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def _resolve(self) -> str:
        return self._func(*self._args, **self._kwargs)

    @typing.override
    def __str__(self) -> str:
        return self._resolve()

    @typing.override
    def __repr__(self) -> str:
        return repr(self._resolve())

    @typing.override
    def __eq__(self, other) -> bool:
        if isinstance(other, _LazyString):
            return self._resolve() == other._resolve()
        return self._resolve() == other

    @typing.override
    def __hash__(self) -> int:
        return hash(self._resolve())

    def __mod__(self, other) -> str:
        return self._resolve() % other


def gettext_lazy(message: str) -> _LazyString:
    """Return a lazy translation proxy for ``message``.

    The translation is evaluated on demand using the active language at the
    time the proxy is coerced to ``str`` -- useful for module-level constants
    and template globals declared before :func:`initialize` runs.
    """
    return _LazyString(gettext, (message,), {})


def ngettext_lazy(singular: str, plural: str, count: int) -> _LazyString:
    """Return a lazy translation proxy for a pluralized message."""
    return _LazyString(ngettext, (singular, plural, count), {})


_ = gettext
