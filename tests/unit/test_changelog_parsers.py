"""Unit tests for ``progress.integrations.changelog.parsers`` (Feature 6).

Covers the universal parser chain:
- ``_extract_version_number`` (spec changelog §8.3 three-step extraction)
- ``parse_markdown_heading`` (Keep-a-Changelog ``## [x.y.z]``)
- ``parse_html_generic`` (lxml heuristic — version-bearing h1-h4 headings)
- ``apply_rule`` (deterministic application of a ``ChangelogRule``)
"""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from progress.errors import ChangelogParseException
from progress.integrations.changelog.parsers import (
    ChangelogRule,
    ChangelogVersion,
    _extract_version_number,
    apply_rule,
    parse_html_generic,
    parse_markdown_heading,
)

_MD_SAMPLE = """# Changelog

## [1.2.0] - 2026-01-15

### Added

- New feature X.

## [1.1.0] - 2025-12-01

### Fixed

- Bug Y.

## 1.0.0

Initial release.
"""

_HTML_SAMPLE = """<html><body>
<h2>Release v3.5.2</h2><article><h3>新功能</h3><ul><li>x</li></ul></article>
<h2>Release v3.4.2</h2><article><h3>修复</h3><ul><li>y</li></ul></article>
</body></html>
"""


class TestExtractVersionNumber:
    """Spec changelog §8.3 three-step extraction pipeline."""

    def test_plain_version(self) -> None:
        assert _extract_version_number("2.0.0") == "2.0.0"

    def test_bracket_v_prefix_date(self) -> None:
        assert _extract_version_number("[v1.2.3] - 2026-01-01") == "1.2.3"

    def test_v_prefix_only(self) -> None:
        assert _extract_version_number("v1.2.2") == "1.2.2"

    def test_uppercase_v_prefix(self) -> None:
        assert _extract_version_number("V3.0.0") == "3.0.0"

    def test_unreleased_treated_as_version(self) -> None:
        assert _extract_version_number("[Unreleased]") == "Unreleased"

    def test_prerelease_cut_off(self) -> None:
        assert _extract_version_number("1.0.0-alpha") == "1.0.0"

    def test_en_dash_date_separator(self) -> None:
        assert _extract_version_number("1.2.3 – 2024-01-01") == "1.2.3"

    def test_em_dash_date_separator(self) -> None:
        assert _extract_version_number("1.2.3 — 2024-01-01") == "1.2.3"

    def test_inline_link_works_incidentally(self) -> None:
        assert _extract_version_number("[1.0.0](https://...)") == "1.0.0"


class TestParseMarkdownHeading:
    def test_parses_three_versions(self) -> None:
        versions = parse_markdown_heading(_MD_SAMPLE)
        assert len(versions) == 3
        assert [v.version for v in versions] == ["1.2.0", "1.1.0", "1.0.0"]

    def test_descriptions_stripped(self) -> None:
        versions = parse_markdown_heading(_MD_SAMPLE)
        assert "New feature X." in versions[0].description
        assert "Bug Y." in versions[1].description

    def test_description_alias_body(self) -> None:
        versions = parse_markdown_heading(_MD_SAMPLE)
        assert versions[0].description == versions[0].body

    def test_no_headings_raises(self) -> None:
        with pytest.raises(ChangelogParseException, match="no markdown version headings"):
            parse_markdown_heading("# plain doc\n\nno versions here")

    def test_one_hash_does_not_match(self) -> None:
        with pytest.raises(ChangelogParseException):
            parse_markdown_heading("# Title\n# 1.0.0\nbody")

    def test_v_prefixed_version_strips_v(self) -> None:
        versions = parse_markdown_heading("## [v2.0.1] - 2026-02-01\nbody")
        assert versions[0].version == "2.0.1"

    def test_brackets_unreleased_kept(self) -> None:
        versions = parse_markdown_heading("## [Unreleased]\nbody")
        assert versions[0].version == "Unreleased"


class TestParseHtmlGeneric:
    """Feature 6 — heuristic HTML parser: version-bearing h1-h4 headings."""

    def test_parses_two_versions(self) -> None:
        versions = parse_html_generic(_HTML_SAMPLE)
        assert [v.version for v in versions] == ["3.5.2", "3.4.2"]

    def test_descriptions_extracted(self) -> None:
        versions = parse_html_generic(_HTML_SAMPLE)
        assert "新功能" in versions[0].description
        assert "修复" in versions[1].description

    def test_no_version_headings_raises(self) -> None:
        with pytest.raises(ChangelogParseException, match="no version-bearing heading"):
            parse_html_generic("<html><body><h2>just text</h2></body></html>")

    def test_empty_raises(self) -> None:
        with pytest.raises(ChangelogParseException, match="empty html input"):
            parse_html_generic("")

    def test_multisegment_version(self) -> None:
        versions = parse_html_generic("<html><body><h2>v7.5.1.2</h2><p>x</p></body></html>")
        assert versions[0].version == "7.5.1.2"


class TestApplyRule:
    """Feature 6 — applying a deterministic ``ChangelogRule``."""

    def test_markdown_rule(self) -> None:
        rule = ChangelogRule(version_selector=None, version_pattern=r"\[(?P<version>\d+\.\d+\.\d+)\]")
        versions = apply_rule(_MD_SAMPLE, rule)
        assert versions[0].version == "1.2.0"
        assert versions[1].version == "1.1.0"

    def test_html_rule_with_body_selector(self) -> None:
        rule = ChangelogRule(
            version_selector="h2",
            version_pattern=r"Release v(?P<version>\d+\.\d+\.\d+)",
            body_selector="article",
        )
        versions = apply_rule(_HTML_SAMPLE, rule)
        assert versions[0].version == "3.5.2"
        assert "x" in versions[0].description

    def test_html_rule_no_body_selector(self) -> None:
        rule = ChangelogRule(
            version_selector="h2",
            version_pattern=r"Release v(?P<version>\d+\.\d+\.\d+)",
        )
        versions = apply_rule(_HTML_SAMPLE, rule)
        assert versions[0].version == "3.5.2"

    def test_rule_no_version_match_raises(self) -> None:
        rule = ChangelogRule(version_selector=None, version_pattern=r"v(?P<version>\d+)")
        with pytest.raises(ChangelogParseException, match="rule: no version matched"):
            apply_rule("## [1.0.0]\nbody", rule)

    def test_rule_no_headings_raises(self) -> None:
        rule = ChangelogRule(version_selector=None, version_pattern=r"(?P<version>\d+)")
        with pytest.raises(ChangelogParseException, match="rule: no headings found"):
            apply_rule("plain text\nno headings", rule)


class TestChangelogRule:
    def test_extra_fields_forbidden(self) -> None:

        with pytest.raises(ValidationError):
            ChangelogRule.model_validate({"version_pattern": r"(?P<version>\d+)", "unknown_field": "x"})


class TestChangelogVersion:
    def test_frozen(self) -> None:
        v = ChangelogVersion(version="1.0.0", description="x")
        with pytest.raises(AttributeError):
            v.version = "2.0.0"  # ty:ignore[invalid-assignment]
