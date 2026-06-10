from pathlib import Path

import pytest

from progress.contrib.proposal.parser import (
    DEPParser,
    EIPParser,
    PEPParser,
    RFCParser,
)
from progress.errors import ProposalParseError


class TestEIPParser:
    def test_parses_frontmatter(self, tmp_path: Path):
        p = tmp_path / "eip-1.md"
        p.write_text(
            "---\n"
            "eip: 1\n"
            "title: Test EIP\n"
            "status: Draft\n"
            "type: Standards Track\n"
            "category: Core\n"
            "author: Alice <alice@example.com>\n"
            "created: 2024-01-02\n"
            "---\n\n# Test\n",
            encoding="utf-8",
        )
        data = EIPParser().parse(str(p))
        assert data.number == "1"
        assert data.title == "Test EIP"
        assert data.raw_status == "Draft"
        assert data.extra.get("category") == "Core"

    def test_moved_stub_title_is_none(self, tmp_path: Path):
        p = tmp_path / "eip-1062.md"
        p.write_text(
            "---\neip: 1062\ncategory: ERC\nstatus: Moved\n---\n",
            encoding="utf-8",
        )
        data = EIPParser().parse(str(p))
        assert data.number == "1062"
        assert data.title is None
        assert data.raw_status == "Moved"

    def test_extract_number(self):
        assert EIPParser().extract_number("/x/y/eip-123.md") == "123"
        assert EIPParser().extract_number("/x/y/erc-20.md") == "20"

    def test_extract_number_no_match(self):
        assert EIPParser().extract_number("/x/y/nope.md") == ""

    def test_matches_pattern(self):
        parser = EIPParser()
        assert parser.matches_pattern("/x/eip-1.md", ["eip-*.md"]) is True
        assert parser.matches_pattern("/x/readme.md", ["eip-*.md"]) is False


class TestPEPParser:
    def test_parses_headers(self, tmp_path: Path):
        p = tmp_path / "pep-0008.rst"
        p.write_text(
            "PEP: 8\n"
            "Title: Style Guide for Python Code\n"
            "Author: Guido\n"
            "Status: Active\n"
            "Type: Process\n"
            "Topic: Python\n"
            "Created: 05-Jul-2001\n\nBody text\n",
            encoding="utf-8",
        )
        data = PEPParser().parse(str(p))
        assert data.number == "8"
        assert data.title == "Style Guide for Python Code"
        assert data.raw_status == "Active"
        assert data.extra.get("topic") == "Python"

    def test_deep_headers(self, tmp_path: Path):
        author_continuations = "\n".join(f"        Author {i}" for i in range(28))
        p = tmp_path / "pep-0733.rst"
        p.write_text(
            "PEP: 733\n"
            f"Author: Author 0,\n{author_continuations}\n"
            "Title: Deep Header Test\n"
            "Status: Final\n"
            "Type: Informational\n\nBody\n",
            encoding="utf-8",
        )
        data = PEPParser().parse(str(p))
        assert data.number == "733"
        assert data.title == "Deep Header Test"

    def test_invalid_header_value_raises(self, tmp_path: Path):
        p = tmp_path / "pep-9999.rst"
        p.write_text(
            "PEP: TBD\nTitle: Test\nStatus: Draft\n\nBody\n",
            encoding="utf-8",
        )
        with pytest.raises(ProposalParseError):
            PEPParser().parse(str(p))

    def test_extract_number(self):
        assert PEPParser().extract_number("/x/pep-0008.rst") == "8"

    def test_extract_number_no_match(self):
        assert PEPParser().extract_number("/x/readme.rst") == ""


class TestRFCParser:
    def test_parses_markdown(self, tmp_path: Path):
        p = tmp_path / "1234-test.md"
        p.write_text(
            "# RFC Title\n\n- Feature Name: test\n- Start Date: 2024-01-01\n",
            encoding="utf-8",
        )
        data = RFCParser().parse(str(p))
        assert data.number == "1234"
        assert data.title == "RFC Title"
        assert data.raw_status == ""

    def test_no_status_raw_empty(self, tmp_path: Path):
        p = tmp_path / "0001-abc.md"
        p.write_text("# Some RFC\n\nBody text\n", encoding="utf-8")
        data = RFCParser().parse(str(p))
        assert data.raw_status == ""

    def test_extract_number(self):
        assert RFCParser().extract_number("/x/1234-test.md") == "1234"

    def test_extract_number_no_match(self):
        assert RFCParser().extract_number("/x/readme.md") == ""


class TestDEPParser:
    def test_rst_field_list_format(self, tmp_path: Path):
        p = tmp_path / "0001-dep-process.rst"
        p.write_text(
            "=================================\n"
            "DEP 1: DEP Purpose and Guidelines\n"
            "=================================\n\n"
            ":DEP: 1\n"
            ":Author: Someone\n"
            ":Status: Final\n"
            ":Type: Process\n"
            ":Created: 2014-04-14\n\nBody\n",
            encoding="utf-8",
        )
        data = DEPParser().parse(str(p))
        assert data.number == "1"
        assert data.raw_status == "Final"
        assert "Purpose" in data.title

    def test_plain_rst_headers(self, tmp_path: Path):
        p = tmp_path / "0001-test.rst"
        p.write_text(
            "DEP: 1\n"
            "Title: DEP Title\n"
            "Status: Draft\n"
            "Type: Standards Track\n"
            "Created: 2024-01-02\n\nBody\n",
            encoding="utf-8",
        )
        data = DEPParser().parse(str(p))
        assert data.number == "1"
        assert data.title == "DEP Title"
        assert data.raw_status == "Draft"

    def test_yaml_frontmatter_format(self, tmp_path: Path):
        p = tmp_path / "0018-mailers.md"
        p.write_text(
            "---\ndep: 18\ntitle: Mailers Framework\nstatus: Draft\n---\n\nBody\n",
            encoding="utf-8",
        )
        data = DEPParser().parse(str(p))
        assert data.number == "18"
        assert data.title == "Mailers Framework"
        assert data.raw_status == "Draft"

    def test_no_number_file(self, tmp_path: Path):
        p = tmp_path / "content-negotiation.rst"
        p.write_text(
            "Title: Content Negotiation\nStatus: Draft\n\nBody\n",
            encoding="utf-8",
        )
        data = DEPParser().parse(str(p))
        assert data.number == ""

    def test_header_directory_mismatch_uses_header(self, tmp_path: Path):
        p = tmp_path / "0014-background-workers.rst"
        p.write_text(
            ":DEP: 14\n:Status: Accepted\n:Title: Background Workers\n\nBody\n",
            encoding="utf-8",
        )
        data = DEPParser().parse(str(p))
        assert data.raw_status == "Accepted"

    def test_extract_number(self):
        assert DEPParser().extract_number("/x/0001-test.rst") == "1"

    def test_extract_number_no_match(self):
        assert DEPParser().extract_number("/x/content-negotiation.rst") == ""
