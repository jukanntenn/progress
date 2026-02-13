from pathlib import Path

import pytest

from progress.errors import ProposalParseError
from progress.contrib.proposal.proposal_parsers import (
    DjangoDEPParser,
    EIPParser,
    PEPParser,
    RustRFCParser,
)


def test_eip_parser_parses_frontmatter(tmp_path: Path):
    p = tmp_path / "eip-1.md"
    p.write_text(
        """---
eip: 1
title: Test EIP
status: Draft
type: Standards Track
category: Core
author: Alice <alice@example.com>
created: 2024-01-02
---

# Test
""",
        encoding="utf-8",
    )

    data = EIPParser().parse(str(p))
    assert data.number == 1
    assert data.title == "Test EIP"
    assert data.status == "Draft"
    assert data.type == "Standards Track"
    assert data.extra.get("category") == "Core"


def test_eip_parser_number_from_filename():
    assert EIPParser().get_proposal_number("/x/y/eip-123.md") == 123
    with pytest.raises(ProposalParseError):
        EIPParser().get_proposal_number("/x/y/nope.md")


def test_pep_parser_parses_headers(tmp_path: Path):
    p = tmp_path / "pep-0008.rst"
    p.write_text(
        """PEP: 8
Title: Style Guide for Python Code
Author: Guido
Status: Active
Type: Process
Topic: Python
Created: 05-Jul-2001

Body text
""",
        encoding="utf-8",
    )

    data = PEPParser().parse(str(p))
    assert data.number == 8
    assert data.title.startswith("Style Guide")
    assert data.status == "Active"
    assert data.type == "Process"
    assert data.extra.get("topic") == "Python"


def test_pep_parser_invalid_header_value_raises(tmp_path: Path):
    p = tmp_path / "pep-9999.rst"
    p.write_text(
        """PEP: TBD
Title: Test
Status: Draft

Body
""",
        encoding="utf-8",
    )
    with pytest.raises(ProposalParseError):
        PEPParser().parse(str(p))


def test_rust_rfc_parser_parses_markdown(tmp_path: Path):
    p = tmp_path / "1234-test.md"
    p.write_text(
        """# RFC Title

Status: Draft
Author: Bob
""",
        encoding="utf-8",
    )
    data = RustRFCParser().parse(str(p))
    assert data.number == 1234
    assert data.title == "RFC Title"
    assert data.status == "Draft"


def test_django_dep_parser_parses_headers(tmp_path: Path):
    p = tmp_path / "0001-test.rst"
    p.write_text(
        """DEP: 1
Title: DEP Title
Status: Draft
Type: Standards Track
Created: 2024-01-02

Body
""",
        encoding="utf-8",
    )
    data = DjangoDEPParser().parse(str(p))
    assert data.number == 1
    assert data.title == "DEP Title"
    assert data.status == "Draft"


def test_django_dep_parser_parses_field_list_style_headers(tmp_path: Path):
    p = tmp_path / "0001-dep-process.rst"
    p.write_text(
        """=================================
DEP 1: DEP Purpose and Guidelines
=================================

:DEP: 1
:Author: Someone
:Status: Final
:Type: Process
:Created: 2014-04-14

Body
""",
        encoding="utf-8",
    )
    data = DjangoDEPParser().parse(str(p))
    assert data.number == 1
    assert data.status == "Final"
    assert data.type == "Process"
    assert "Purpose" in data.title


def test_django_dep_parser_invalid_header_value_raises(tmp_path: Path):
    p = tmp_path / "0002-test.rst"
    p.write_text(
        """DEP: TBD
Title: DEP Title
Status: Draft

Body
""",
        encoding="utf-8",
    )
    with pytest.raises(ProposalParseError):
        DjangoDEPParser().parse(str(p))
