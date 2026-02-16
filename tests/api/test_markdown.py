from progress.api.markdown import render_markdown


def test_render_markdown_empty():
    assert render_markdown("") == ""
    assert render_markdown(None) == ""


def test_render_markdown_basic():
    result = render_markdown("# Hello")
    assert "<h1>Hello</h1>" in result


def test_render_markdown_details_element():
    content = """<details>
<summary>Click me</summary>

Hidden content here.

</details>"""
    result = render_markdown(content)
    assert "<details>" in result
    assert "<summary>Click me</summary>" in result
    assert "Hidden content here" in result


def test_render_markdown_preserves_html():
    content = "<strong>bold</strong> and *italic*"
    result = render_markdown(content)
    assert "<strong>bold</strong>" in result
    assert "<em>italic</em>" in result


def test_render_markdown_code_block():
    content = "```python\nprint('hello')\n```"
    result = render_markdown(content)
    assert "<pre>" in result
    assert "<code" in result
