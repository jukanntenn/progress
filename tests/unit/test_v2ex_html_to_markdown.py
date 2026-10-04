"""Unit tests for the v2ex topic-body HTML→markdown converter (spec v2ex §2).

Pure-function tests over :func:`progress.integrations.v2ex.parser.html_to_markdown`:
formatting fidelity for the V2EX ``markdown_body`` subset, and the three-stage
allowlist security chain (nh3 strip → markdownify ``convert`` allowlist →
``escape_misc``) that must never let untrusted HTML re-emerge as markup.
"""

from __future__ import annotations

from progress.integrations.v2ex.parser import html_to_markdown
from progress.utils.markdown import render_markdown


class TestFormattingFidelity:
    def test_paragraphs_links_images(self) -> None:
        html = (
            '<div class="topic_content"><div class="markdown_body">'
            '<p>第一段。</p><p>看 <a href="https://example.com/a" title="提示">链接</a> 和 '
            '<img src="https://example.com/i.png" alt="图">。</p>'
            "</div></div>"
        )
        md = html_to_markdown(html)
        assert "第一段。" in md
        assert '[链接](https://example.com/a "提示")' in md
        assert "![图](https://example.com/i.png)" in md

    def test_code_fence_keeps_language_from_code_child(self) -> None:
        html = (
            '<div class="topic_content"><pre class="prettyprint">'
            '<code class="language-rust">fn main() {}</code></pre></div>'
        )
        assert html_to_markdown(html) == "```rust\nfn main() {}\n```"

    def test_blockquote_lists_and_inline_marks(self) -> None:
        html = (
            '<div class="topic_content"><blockquote><p>引用</p></blockquote>'
            "<ul><li>一<em>斜体</em></li><li>二<strong>粗体</strong></li></ul>"
            "<ol><li>第一</li><li>第二</li></ol>"
            "<p><del>删</del> <code>x = 1</code></p></div>"
        )
        md = html_to_markdown(html)
        assert "> 引用" in md
        assert "- 一*斜体*" in md
        assert "- 二**粗体**" in md
        assert "1. 第一" in md and "2. 第二" in md
        assert "~~删~~" in md
        assert "`x = 1`" in md

    def test_empty_and_blank_inputs_return_empty(self) -> None:
        assert html_to_markdown("") == ""
        assert html_to_markdown("   ") == ""


class TestSecurityChain:
    def test_script_tag_and_contents_removed(self) -> None:
        html = '<div class="topic_content"><p>前</p><script>alert(1)</script><p>后</p></div>'
        md = html_to_markdown(html)
        assert "alert" not in md
        assert "<script" not in md
        assert "前" in md and "后" in md

    def test_literal_angle_bracket_text_cannot_become_markup(self) -> None:
        html = '<div class="topic_content"><p>a &lt;script&gt; b &lt;iframe&gt; c</p></div>'
        md = html_to_markdown(html)
        # markdownify escape_misc backslash-escapes the angle brackets, so the
        # text survives as text; the real guarantee is the project's own
        # render chain (markdown-it html=True + nh3) producing no markup.
        assert "script" in md and "iframe" in md
        rendered = render_markdown(md)
        assert "<script" not in rendered and "<iframe" not in rendered

    def test_javascript_href_dropped_link_kept_as_text(self) -> None:
        html = '<div class="topic_content"><p><a href="javascript:evil()">点我</a></p></div>'
        md = html_to_markdown(html)
        assert "javascript:" not in md
        assert "点我" in md

    def test_unknown_tags_unwrap_to_text_never_emitted(self) -> None:
        html = (
            '<div class="topic_content"><span onclick="x()">span 文本</span>'
            '<iframe src="https://evil.example"></iframe><p>ok</p></div>'
        )
        md = html_to_markdown(html)
        assert "<span" not in md and "<iframe" not in md
        assert "span 文本" in md
        assert "evil.example" not in md

    def test_disallowed_attributes_stripped(self) -> None:
        html = '<div class="topic_content"><p style="color:red" onclick="p()">文本</p></div>'
        md = html_to_markdown(html)
        assert "文本" in md
        assert "style" not in md and "onclick" not in md
