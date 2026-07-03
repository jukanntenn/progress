"""Tests for the internationalization module."""

from __future__ import annotations

import pytest

from progress import i18n


@pytest.fixture(autouse=True)
def _reset_i18n():
    """Reset i18n state between tests for isolation."""
    yield
    i18n._translations.clear()
    i18n._ui_language = "en"


def test_initialize_sets_language():
    i18n.initialize("zh-hans")
    assert i18n.get_language() == "zh-hans"


def test_default_language_is_en():
    assert i18n.get_language() == "en"


def test_gettext_returns_msgid_without_translation():
    msg = i18n.gettext("Some untranslated string")
    assert msg == "Some untranslated string"


def test_gettext_alias_underscore():
    assert i18n._ is i18n.gettext


def test_ngettext_singular_form():
    assert i18n.ngettext("one item", "many items", 1) == "one item"


def test_ngettext_plural_form():
    assert i18n.ngettext("one item", "many items", 5) == "many items"


def test_override_switches_language_and_restores():
    i18n.initialize("en")
    assert i18n.get_language() == "en"

    with i18n.override("zh-hans"):
        assert i18n.get_language() == "zh-hans"

    assert i18n.get_language() == "en"


def test_override_with_none():
    i18n.initialize("zh-hans")
    with i18n.override(None):
        assert i18n.get_language() is None
    assert i18n.get_language() == "zh-hans"


def test_override_restores_on_exception():
    i18n.initialize("en")
    with pytest.raises(RuntimeError):
        with i18n.override("zh-hans"):
            raise RuntimeError("boom")
    assert i18n.get_language() == "en"


def test_override_is_per_thread_independent():
    import threading

    i8n_seen = {}

    def worker():
        with i18n.override("zh-hans"):
            i8n_seen["worker"] = i18n.get_language()

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert i8n_seen["worker"] == "zh-hans"
    assert i18n.get_language() == "en"


def test_override_is_nested():
    i18n.initialize("en")
    with i18n.override("zh-hans"):
        assert i18n.get_language() == "zh-hans"
        with i18n.override("fr"):
            assert i18n.get_language() == "fr"
        assert i18n.get_language() == "zh-hans"
    assert i18n.get_language() == "en"


def test_translation_catalog_is_cached():
    i18n.gettext("cache probe")
    cache_after_first = dict(i18n._translations)

    i18n.gettext("cache probe again")
    assert i18n._translations == cache_after_first


def test_gettext_lazy_resolves_at_use_time():
    i18n.initialize("en")
    lazy = i18n.gettext_lazy("Deferred message")
    assert isinstance(lazy, i18n._LazyString)
    assert str(lazy) == "Deferred message"


def test_gettext_lazy_reflects_active_language_change():
    i18n.initialize("en")
    lazy = i18n.gettext_lazy("Some message")

    with i18n.override("zh-hans"):
        resolved_in_override = str(lazy)

    assert resolved_in_override == "Some message"


def test_lazy_string_equality_and_mod():
    a = i18n.gettext_lazy("hello")
    b = i18n.gettext_lazy("hello")
    assert a == b
    assert a == "hello"
    template = i18n.gettext_lazy("Count: %d")
    assert template % 5 == "Count: 5"
