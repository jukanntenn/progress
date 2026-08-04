"""Unit tests for ``progress.utils.text`` (spec 09)."""

from __future__ import annotations

from progress.utils.text import slugify, truncate, url_safe


class TestTruncate:
    def test_short_text_unchanged(self) -> None:
        assert truncate("hello", 10) == "hello"

    def test_long_text_truncated_with_suffix(self) -> None:
        out = truncate("abcdefghij", 5)
        assert out == "abcde..."

    def test_custom_suffix(self) -> None:
        out = truncate("abcdefghij", 5, suffix="…")
        assert out == "abcde…"

    def test_exact_length_no_truncation(self) -> None:
        assert truncate("abc", 3) == "abc"

    def test_explicit_max_length(self) -> None:
        assert truncate("a" * 200, 200) == "a" * 200
        assert truncate("a" * 201, 200).endswith("...")


class TestSlugify:
    def test_basic(self) -> None:
        assert slugify("Hello World") == "hello-world"

    def test_punctuation_replaced(self) -> None:
        assert slugify("foo! bar? baz.") == "foo-bar-baz"

    def test_multiple_separators_collapsed(self) -> None:
        assert slugify("foo---bar") == "foo-bar"

    def test_leading_trailing_dashes_stripped(self) -> None:
        assert slugify("---foo---") == "foo"

    def test_max_length(self) -> None:
        out = slugify("a" * 100, max_length=10)
        assert len(out) <= 10
        assert out == "aaaaaaaaaa"

    def test_empty_returns_x(self) -> None:
        assert slugify("") == "x"

    def test_all_punctuation_returns_x(self) -> None:
        assert slugify("!!!???") == "x"


class TestUrlSafe:
    def test_ascii_passthrough(self) -> None:
        assert url_safe("abc123") == "abc123"

    def test_spaces_encoded(self) -> None:
        assert url_safe("a b") == "a%20b"

    def test_special_chars_encoded(self) -> None:
        assert url_safe("a/b") == "a%2Fb"
        assert url_safe("a?b") == "a%3Fb"
