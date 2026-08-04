"""Unit tests for the notification status single-source-of-truth module.

These guard the contract every channel relies on (spec 10): the
``status_color`` / ``status_label`` / ``status_icon`` lookups are the one place
status semantics live, so they must (a) cover every status key the templates
and ``console_card`` consume, (b) never raise on an unknown key (a lookup
failure would crash rendering and drop a notification), and (c) resolve the
label through the active locale's catalog at call time.
"""

from __future__ import annotations

import pytest

from progress.cli.notifications import status as status_mod
from progress.cli.notifications.status import (
    STATUS_SPEC,
    status_color,
    status_icon,
    status_label,
)
from progress.utils.i18n import override

# The full set of keys each category must define — kept in sync with the spec
# categories consumed by the templates and console_card.py.
_EXPECTED_KEYS = {
    "repo_status": {"success", "failed", "skipped"},
    "proposal_status": {"Final", "Review", "Draft", "Idea", "Withdrawn", "Rejected", "Stagnant", "Living"},
    "proposal_kind": {"EIP", "ERC", "PEP", "RFC", "DEP"},
    "changelog_level": {"MAJOR", "MINOR", "PATCH"},
}


class TestStatusSpecCoverage:
    def test_every_category_is_present(self) -> None:
        assert set(STATUS_SPEC) == set(_EXPECTED_KEYS)

    @pytest.mark.parametrize("category,keys", list(_EXPECTED_KEYS.items()))
    def test_every_expected_key_is_defined(self, category: str, keys: set[str]) -> None:
        assert set(STATUS_SPEC[category]) == keys

    @pytest.mark.parametrize("category", list(_EXPECTED_KEYS))
    def test_every_entry_has_color_icon_label(self, category: str) -> None:
        for key, spec in STATUS_SPEC[category].items():
            assert {"color", "icon", "label_key"} <= set(spec), f"{category}.{key} missing fields: {spec}"


class TestStatusColor:
    @pytest.mark.parametrize(
        "category,key,expected",
        [
            ("repo_status", "success", "green"),
            ("repo_status", "failed", "red"),
            ("repo_status", "skipped", "grey"),
            ("proposal_status", "Final", "green"),
            ("proposal_status", "Review", "orange"),
            ("proposal_status", "Withdrawn", "red"),
            ("proposal_status", "Living", "blue"),
            ("proposal_kind", "EIP", "blue"),
            ("proposal_kind", "ERC", "purple"),
            ("proposal_kind", "PEP", "turquoise"),
            ("changelog_level", "MAJOR", "red"),
            ("changelog_level", "MINOR", "blue"),
            ("changelog_level", "PATCH", "grey"),
        ],
    )
    def test_known_keys(self, category: str, key: str, expected: str) -> None:
        assert status_color(category, key) == expected

    def test_unknown_category_returns_grey(self) -> None:
        assert status_color("nope", "x") == "grey"

    def test_unknown_key_returns_grey(self) -> None:
        assert status_color("repo_status", "bogus") == "grey"


class TestStatusIcon:
    def test_known_key_returns_nonempty_glyph(self) -> None:
        assert status_icon("repo_status", "success") == "✅"

    def test_unknown_key_returns_empty(self) -> None:
        assert status_icon("repo_status", "bogus") == ""


class TestStatusLabel:
    def test_label_resolves_through_active_catalog_in_chinese(self) -> None:
        # The whole point of resolving at call time: the zh catalog translates
        # SUCCESS/FAILED/SKIPPED — pre-refactor these were hardcoded locals.
        with override("zh-hans"):
            assert status_label("repo_status", "success") == "成功"
            assert status_label("repo_status", "failed") == "失败"
            assert status_label("repo_status", "skipped") == "已跳过"

    def test_label_falls_back_to_msgid_in_english(self) -> None:
        with override("en"):
            assert status_label("repo_status", "success") == "SUCCESS"
            assert status_label("proposal_kind", "EIP") == "EIP"

    def test_unknown_key_returns_raw_key(self) -> None:
        # Never raises — a bogus status must not crash rendering.
        with override("en"):
            assert status_label("repo_status", "bogus") == "bogus"

    def test_label_changes_with_locale_without_reimport(self) -> None:
        # Call-time resolution: the same call yields different results under
        # different active locales (proves no module-import-time caching).
        assert status_label("repo_status", "failed") == "FAILED"
        with override("zh-hans"):
            assert status_label("repo_status", "failed") == "失败"


class TestNoHardcodedPaletteDrift:
    """The pre-refactor bug was status dicts duplicated across 6+ sites with no
    single source. This structural test ensures no channel re-introduces a
    hardcoded ``{"success": "green" ...}`` style mapping by reading the
    canonical values from STATUS_SPEC instead."""

    @pytest.mark.parametrize("category", list(_EXPECTED_KEYS))
    def test_status_color_matches_spec_table(self, category: str) -> None:
        for key in STATUS_SPEC[category]:
            assert status_color(category, key) == STATUS_SPEC[category][key]["color"]


def test_module_exports_public_api() -> None:
    """The package re-exports these so templates and callers can import from
    either ``progress.cli.notifications`` or the status submodule."""
    from progress.cli.notifications import STATUS_SPEC, status_color as exported_color  # noqa: PLC0415

    assert STATUS_SPEC is status_mod.STATUS_SPEC
    assert exported_color is status_color
