from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from progress.contrib.changelog.changelog_parsers import (
    HTMLChineseVersionParser,
    MarkdownHeadingParser,
)
from progress.errors import ChangelogParseError


def test_markdown_heading_parser_parses_versions_and_descriptions():
    content = """# Changelog

## 2.0.0
Added something.

- Item A

## 1.0.0
Initial release.
"""

    parser = MarkdownHeadingParser()
    entries = parser.parse(content)

    assert [e.version for e in entries] == ["2.0.0", "1.0.0"]
    assert "Added something." in entries[0].description
    assert "Initial release." in entries[1].description


def test_markdown_heading_parser_extracts_version_from_brackets_and_v_prefix():
    content = """## [v1.2.3] - 2026-01-01
Hello

## v1.2.2
World
"""

    parser = MarkdownHeadingParser()
    entries = parser.parse(content)

    assert [e.version for e in entries] == ["1.2.3", "1.2.2"]


def test_html_chinese_version_parser_parses_utools_style_versions():
    content = """<html><body>
<h2>uTools v7.5.1</h2>
<p>Fix: A</p>
<h2>uTools v7.5.0</h2>
<p>Feat: B</p>
</body></html>"""

    parser = HTMLChineseVersionParser()
    entries = parser.parse(content)

    assert [e.version for e in entries] == ["7.5.1", "7.5.0"]
    assert "Fix: A" in entries[0].description


async def test_fetch_wraps_request_errors_as_changelog_parse_error():
    import progress.contrib.changelog.changelog_parsers as cp

    with patch("progress.contrib.changelog.changelog_parsers.aiohttp.ClientSession") as mock_session_cls:
        session = MagicMock()
        session.get.side_effect = aiohttp.ClientError("boom")

        mock_session_cls.return_value.__aenter__.return_value = session

        parser = MarkdownHeadingParser()
        with pytest.raises(ChangelogParseError, match="Failed to fetch changelog"):
            await parser.fetch("https://example.com/changelog")


async def test_fetch_decodes_utf8_when_response_encoding_is_latin1():
    import progress.contrib.changelog.changelog_parsers as cp

    payload = "uTools v7.5.1 【优化】主搜索框 UI 优化".encode()

    with patch("progress.contrib.changelog.changelog_parsers.aiohttp.ClientSession") as mock_session_cls:
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        resp.read = AsyncMock(return_value=payload)
        resp.charset = "iso-8859-1"

        session = MagicMock()
        session.get.return_value.__aenter__.return_value = resp
        session.get.return_value.__aexit__.return_value = None

        mock_session_cls.return_value.__aenter__.return_value = session

        parser = HTMLChineseVersionParser()
        text = await parser.fetch("https://example.com/changelog")
        assert "【优化】" in text


def test_markdown_heading_parser_raises_on_missing_versions():
    parser = MarkdownHeadingParser()
    with pytest.raises(ChangelogParseError, match="No version headings"):
        parser.parse("# No versions here")


def test_html_parser_raises_on_missing_versions():
    parser = HTMLChineseVersionParser()
    with pytest.raises(ChangelogParseError, match="No version patterns"):
        parser.parse("<html><body><p>no versions</p></body></html>")

