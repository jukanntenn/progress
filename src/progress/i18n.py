"""Internationalization (i18n) support using gettext."""

import gettext as gettext_module
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DOMAIN = "progress"
LOCALE_DIR = Path(__file__).parent / "locales"

# Thread-local storage for translations
_thread_local = threading.local()

# Initialization state
_initialized = False
_ui_language = "en"


def initialize(ui_language: str = "en") -> None:
    """Initialize translation system with language configuration.

    This must be called once at application startup before using any translation functions.

    Args:
        ui_language: Language code for UI/reports/notifications
    """
    global _initialized, _ui_language

    _ui_language = ui_language
    _initialized = True

    logger.info(f"Translation initialized: UI={ui_language}")


def _get_translation() -> gettext_module.GNUTranslations:
    """Get UI translation (thread-safe with lazy initialization)."""
    if not hasattr(_thread_local, "translation"):
        _thread_local.translation = _load_translation(_ui_language)
    return _thread_local.translation


def gettext(message: str) -> str:
    """Translate UI message (reports, notifications, user interface).

    Args:
        message: Message to translate

    Returns:
        Translated message
    """
    return _get_translation().gettext(message)


def ngettext(singular: str, plural: str, count: int) -> str:
    """Translate UI message with plural form support.

    Args:
        singular: Singular form message
        plural: Plural form message
        count: Count for plural selection

    Returns:
        Translated message in appropriate form
    """
    return _get_translation().ngettext(singular, plural, count)


def _load_translation(language: str | None = None) -> gettext_module.GNUTranslations:
    """Load gettext translation object with fallback.

    Args:
        language: Language code (e.g., "zh", "en", "zh_CN")
                 If None, returns NullTranslations (fallback to msgid)

    Returns:
        GNUTranslations object with fallback enabled
    """
    if not language:
        logger.debug(
            "No language specified, using NullTranslations (fallback to English)"
        )
        return gettext_module.NullTranslations()

    try:
        translation = gettext_module.translation(
            domain=DOMAIN,
            localedir=str(LOCALE_DIR),
            languages=[language],
            fallback=True,
        )
        logger.info(f"Loaded translation for language: {language}")
        return translation
    except Exception as e:
        logger.warning(
            f"Failed to load translation for {language}: {e}, using fallback"
        )
        return gettext_module.NullTranslations()
