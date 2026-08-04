"""Unit tests for ``progress.utils.i18n`` (spec 11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
import pytest

from progress.utils.i18n import (
    DEFAULT_LOCALE,
    DOMAIN,
    get_locale,
    gettext,
    install_locale_dir,
    negotiate_locale,
    ngettext,
    npgettext,
    override,
    pgettext,
    set_locale,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _reset_locale():
    """Reset the locale ContextVar to default after each test."""
    set_locale(DEFAULT_LOCALE)
    yield
    set_locale(DEFAULT_LOCALE)


class TestLocaleGetSet:
    def test_default_is_en(self) -> None:
        assert get_locale() == "en"

    def test_set_lowercased(self) -> None:
        set_locale("ZH-Hans")
        assert get_locale() == "zh-hans"

    def test_set_empty_falls_back(self) -> None:
        set_locale("")
        assert get_locale() == DEFAULT_LOCALE


class TestOverride:
    def test_override_restores_previous(self) -> None:
        set_locale("en")
        with override("zh-hans"):
            assert get_locale() == "zh-hans"
        assert get_locale() == "en"

    def test_override_lowercased(self) -> None:
        with override("ZH-Hans"):
            assert get_locale() == "zh-hans"

    def test_override_empty_falls_back(self) -> None:
        with override(""):
            assert get_locale() == DEFAULT_LOCALE

    def test_override_restores_on_exception(self) -> None:
        set_locale("en")
        with pytest.raises(RuntimeError), override("zh-hans"):
            assert get_locale() == "zh-hans"
            raise RuntimeError("boom")
        assert get_locale() == "en"


class TestGettext:
    def test_unknown_message_returns_input(self) -> None:
        set_locale("en")
        assert gettext("definitely-not-translated-msg") == "definitely-not-translated-msg"

    def test_zh_hans_translation_loaded(self) -> None:
        set_locale("zh-hans")
        out = gettext("Repository details")
        assert out == "仓库明细"

    def test_unknown_locale_falls_back_to_input(self) -> None:
        set_locale("xx-yy")
        assert gettext("Repository details") == "Repository details"


class TestNgettext:
    def test_en_singular(self) -> None:
        set_locale("en")
        assert ngettext("commit", "commits", 1) == "commit"

    def test_en_plural(self) -> None:
        set_locale("en")
        assert ngettext("commit", "commits", 5) == "commits"

    def test_en_zero_is_plural(self) -> None:
        set_locale("en")
        assert ngettext("commit", "commits", 0) == "commits"

    def test_zh_hans_uses_single_form(self) -> None:
        set_locale("zh-hans")
        assert ngettext("commit", "commits", 1) == "次提交"
        assert ngettext("commit", "commits", 5) == "次提交"


class TestPgettext:
    def test_en_unknown_returns_message(self) -> None:
        set_locale("en")
        assert pgettext("month", "May") == "May"

    def test_no_leaky_separator_on_missing_context(self) -> None:
        set_locale("zh-hans")
        out = pgettext("nonexistent-context", "Repository details")
        assert "\x04" not in out
        assert out == "Repository details"

    def test_zh_hans_missing_context_returns_untranslated(self) -> None:
        set_locale("zh-hans")
        out = pgettext("some-context", "Repository details")
        assert out == "Repository details"


class TestNpgettext:
    def test_en_singular(self) -> None:
        set_locale("en")
        assert npgettext("ctx", "item", "items", 1) == "item"

    def test_en_plural(self) -> None:
        set_locale("en")
        assert npgettext("ctx", "item", "items", 5) == "items"

    def test_no_leaky_separator_on_missing_context(self) -> None:
        set_locale("zh-hans")
        out = npgettext("nonexistent-context", "commit", "commits", 1)
        assert "\x04" not in out

    def test_falls_back_to_plain_ngettext_when_context_missing(self) -> None:
        set_locale("zh-hans")
        out = npgettext("nonexistent-context", "commit", "commits", 5)
        assert out == "次提交"


class TestNegotiateLocale:
    def test_empty_returns_default(self) -> None:
        assert negotiate_locale("") == DEFAULT_LOCALE

    def test_single_match(self) -> None:
        assert negotiate_locale("zh-hans") == "zh-hans"

    def test_multiple_with_q(self) -> None:
        out = negotiate_locale("en;q=0.9, zh-hans;q=1.0")
        assert out == "zh-hans"

    def test_falls_back_to_base_subtag(self) -> None:
        out = negotiate_locale("zh-Hant")
        assert out in {"zh-hans", DEFAULT_LOCALE}

    def test_unknown_returns_default(self) -> None:
        assert negotiate_locale("xx-yy, zz") == DEFAULT_LOCALE


class TestConstants:
    def test_domain(self) -> None:
        assert DOMAIN == "progress"

    def test_default_locale(self) -> None:
        assert DEFAULT_LOCALE == "en"


class TestInstallLocaleDir:
    def test_load_from_custom_dir_does_not_raise(self, tmp_path: Path) -> None:

        locale_dir = tmp_path / "zh-hans" / "LC_MESSAGES"
        locale_dir.mkdir(parents=True)
        mo_path = locale_dir / f"{DOMAIN}.mo"

        catalog = Catalog(locale=None, domain=DOMAIN)
        catalog.add("custom-test-msg", "translated-test-msg")
        with mo_path.open("wb") as fp:
            write_mo(fp, catalog)

        install_locale_dir(tmp_path, locale="zh-hans")
