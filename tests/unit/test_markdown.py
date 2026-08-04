"""Unit tests for ``progress.utils.markdown`` (spec 09).

CommonMark + nh3 sanitize — verify safe output and that dangerous tags are
stripped.
"""

from __future__ import annotations

from progress.utils.markdown import downgrade_headings, render_inline, render_markdown


class TestRenderMarkdown:
    def test_empty_returns_empty(self) -> None:
        assert render_markdown("") == ""

    def test_none_returns_empty(self) -> None:
        assert render_markdown(None) == ""  # ty:ignore[invalid-argument-type]

    def test_heading(self) -> None:
        out = render_markdown("# Title")
        assert "<h1>Title</h1>" in out

    def test_paragraph(self) -> None:
        out = render_markdown("hello world")
        assert "<p>hello world</p>" in out

    def test_code_block(self) -> None:
        out = render_markdown("```\nprint('hi')\n```")
        assert "<pre>" in out
        assert "<code>" in out
        assert "print('hi')" in out

    def test_inline_code(self) -> None:
        out = render_markdown("`foo`")
        assert "<code>foo</code>" in out

    def test_link(self) -> None:
        out = render_markdown("[Progress](https://github.com/jukanntenn/progress)")
        assert '<a href="https://github.com/jukanntenn/progress"' in out
        assert ">Progress</a>" in out

    def test_script_tag_stripped(self) -> None:
        out = render_markdown("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "alert(1)" not in out

    def test_iframe_tag_stripped(self) -> None:
        out = render_markdown('<iframe src="evil"></iframe>')
        assert "<iframe" not in out

    def test_javascript_url_stripped(self) -> None:
        out = render_markdown("[click](javascript:alert(1))")
        assert '<a href="javascript:' not in out

    def test_unsafe_html_attr_stripped(self) -> None:
        out = render_markdown('<p onclick="alert(1)">hi</p>')
        assert "onclick" not in out


class TestRenderInline:
    def test_empty(self) -> None:
        assert render_inline("") == ""

    def test_inline_no_paragraph(self) -> None:
        out = render_inline("**bold**")
        assert "<strong>bold</strong>" in out
        assert "<p>" not in out

    def test_inline_link(self) -> None:
        out = render_inline("[Progress](https://github.com/jukanntenn/progress)")
        assert "<a href=" in out
        assert "Progress</a>" in out


class TestDowngradeHeadings:
    def test_no_headings(self) -> None:
        assert downgrade_headings("plain text\nno headings") == "plain text\nno headings"

    def test_shift_h2_to_h3(self) -> None:
        assert downgrade_headings("## title\n### sub") == "### title\n#### sub"

    def test_shift_h1_to_h3(self) -> None:
        assert downgrade_headings("# a\n## b\n### c") == "### a\n#### b\n##### c"

    def test_already_h4_no_shift(self) -> None:
        assert downgrade_headings("#### x") == "#### x"

    def test_overflow_no_shift(self) -> None:
        # h1 + h6 → shift=2 → h6+2=8>6 → 整体不降级
        assert downgrade_headings("# a\n###### b") == "# a\n###### b"

    def test_fence_code_block_protected(self) -> None:
        text = "## title\n```python\n# comment not heading\n```\n## another"
        result = downgrade_headings(text)
        assert "```python\n# comment not heading\n```" in result
        assert result.startswith("### title")

    def test_empty(self) -> None:
        assert downgrade_headings("") == ""

    def test_tilde_fence(self) -> None:
        text = "## title\n~~~\n# not heading\n~~~\n## x"
        result = downgrade_headings(text)
        assert "~~~\n# not heading\n~~~" in result
        assert result.startswith("### title")
