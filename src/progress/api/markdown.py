from markdown_it import MarkdownIt
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin

mdit = (
    MarkdownIt("commonmark", {"breaks": True, "html": True})
    .use(front_matter_plugin)
    .use(footnote_plugin)
)


def render_markdown(content: str | None) -> str:
    if not content:
        return ""
    return mdit.render(content)
