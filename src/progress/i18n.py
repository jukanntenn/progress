"""Internationalization (i18n) support using gettext."""

import gettext
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DOMAIN = "progress"
LOCALE_DIR = Path(__file__).parent / "locales"


def get_translation(language: str | None = None) -> gettext.GNUTranslations:
    """Get gettext translation object with fallback.

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
        return gettext.NullTranslations()

    try:
        translation = gettext.translation(
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
        return gettext.NullTranslations()
