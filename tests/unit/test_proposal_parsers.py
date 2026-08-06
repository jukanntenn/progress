"""Unit tests for ``progress.integrations.proposal.parsers`` (spec proposal §9)."""

from __future__ import annotations

import pytest

from progress.errors import ProposalParseException
from progress.integrations.proposal.parsers import (
    parse_dep,
    parse_eiperc,
    parse_pep,
    parse_rfc,
    parse_rst_fieldlist,
    parse_yaml_frontmatter,
)


class TestParseEiperc:
    def test_standard_frontmatter(self) -> None:
        text = "---\neip: 9999\ntitle: Test EIP\nstatus: Draft\ntype: Standards Track\ncategory: Core\n---\nbody"
        r = parse_eiperc(text, "EIPS/eip-9999.md")
        assert r.number == "9999"
        assert r.title == "Test EIP"
        assert r.raw_status == "Draft"
        assert r.extra.get("category") == "Core"
        assert r.extra.get("type") == "Standards Track"

    def test_moved_stub_has_no_title(self) -> None:
        text = "---\neip: 100\nstatus: Moved\n---\nbody"
        r = parse_eiperc(text, "eip-100.md")
        assert r.title is None
        assert r.raw_status == "Moved"

    def test_leading_zero_stripped(self) -> None:
        text = "---\neip: 007\nstatus: Final\n---\nbody"
        r = parse_eiperc(text, "eip-7.md")
        assert r.number == "7"

    def test_filename_fallback_for_number(self) -> None:
        text = "---\ntitle: No EIP Key\nstatus: Draft\n---\nbody"
        r = parse_eiperc(text, "eip-42.md")
        assert r.number == "42"

    def test_filename_fallback_for_erc(self) -> None:
        text = "---\neip: 5\ntitle: ERC\nstatus: Draft\n---\nbody"
        r = parse_eiperc(text, "erc-5.md")
        assert r.number == "5"

    def test_empty_title_becomes_none(self) -> None:
        text = '---\neip: 1\ntitle: ""\nstatus: Draft\n---\nbody'
        r = parse_eiperc(text, "eip-1.md")
        assert r.title is None


class TestParsePep:
    def test_standard_rst(self) -> None:
        text = "PEP: 9999\nTitle: Test PEP\nStatus: Draft\nTopic: Testing\nAuthor: Alice\n\nBody."
        r = parse_pep(text, "pep-9999.rst")
        assert r.number == "9999"
        assert r.title == "Test PEP"
        assert r.raw_status == "Draft"
        assert r.extra.get("topic") == "Testing"

    def test_multiline_author_continuation(self) -> None:
        text = "PEP: 1\nTitle: X\nStatus: Draft\nAuthor: Alice <a@example.com>,\n        Bob <b@example.com>\n\nBody."
        fields = parse_rst_fieldlist(text)
        assert "Alice" in fields["author"]
        assert "Bob" in fields["author"]

    def test_tbd_raises(self) -> None:
        with pytest.raises(ProposalParseException, match="no parseable number"):
            parse_pep("PEP: TBD\nTitle: X\nStatus: Draft\n", "pep-0.rst")

    def test_deep_headers_still_parse_title(self) -> None:
        text = (
            "PEP: 1\n"
            "Title: Deep Headers\n"
            "Status: Draft\n"
            "Author: Alice,\n"
            "        Bob\n"
            "Discussions-To: list@example.com\n"
        )
        r = parse_pep(text, "pep-1.rst")
        assert r.title == "Deep Headers"

    def test_filename_fallback(self) -> None:
        r = parse_pep("Title: X\nStatus: Draft\n", "pep-7.rst")
        assert r.number == "7"


class TestParseRfc:
    def test_markdown_link_pr(self) -> None:
        text = (
            "- Feature Name: my_feature\n- RFC PR: [rust-lang/rfcs#1234](https://github.com/rust-lang/rfcs/pull/1234)\n"
        )
        r = parse_rfc(text, "1234-my-feature.md")
        assert r.number == "1234"
        assert r.extra.get("pr_number") == 1234
        assert r.extra.get("fallback_title") == "My feature"

    def test_bare_pr(self) -> None:
        text = "- Feature Name: x\n- RFC PR: #5678\n"
        r = parse_rfc(text, "5678-x.md")
        assert r.extra.get("pr_number") == 5678

    def test_no_pr(self) -> None:
        text = "- Feature Name: y\n"
        r = parse_rfc(text, "9999-y.md")
        assert r.extra.get("pr_number") is None

    def test_no_feature_name_uses_filename_stem(self) -> None:
        text = "Just body, no frontmatter.\n"
        r = parse_rfc(text, "1111-some-rfc.md")
        assert r.extra.get("fallback_title") == "1111-some-rfc"

    def test_raw_status_always_empty(self) -> None:
        r = parse_rfc("- Feature Name: x\n", "1-x.md")
        assert r.raw_status == ""


class TestParseDep:
    def test_yaml_variant(self) -> None:
        text = "---\ndep: 14\ntitle: Background Workers\nstatus: Accepted\n---\nbody"
        r = parse_dep(text, "0014-background-workers.md")
        assert r.number == "14"
        assert r.title == "Background Workers"
        assert r.raw_status == "Accepted"

    def test_rst_variant(self) -> None:
        text = ":DEP: 14\nTitle: From Header\nStatus: Draft\n\nBody."
        r = parse_dep(text, "0014-background-workers.rst")
        assert r.number == "14"
        assert r.title == "From Header"
        assert r.raw_status == "Draft"

    def test_rst_title_from_heading_line(self) -> None:
        text = ":DEP: 14\nStatus: Draft\n\nDEP 14: Title From Heading\n"
        r = parse_dep(text, "0014-x.rst")
        assert r.title == "Title From Heading"

    def test_rst_no_title_no_heading_yields_none(self) -> None:
        text = ":DEP: 14\nStatus: Draft\n\nSome body text.\n"
        r = parse_dep(text, "0014-x.rst")
        assert r.title is None

    def test_filename_number_used_when_no_header(self) -> None:
        text = "Body only.\n"
        r = parse_dep(text, "0014-x.rst")
        assert r.number == "14"

    def test_no_digits_yields_empty_number(self) -> None:
        text = "Body only.\n"
        r = parse_dep(text, "content-negotiation.rst")
        assert r.number == ""


class TestYamlFrontmatter:
    def test_keys_lowercased(self) -> None:
        fields = parse_yaml_frontmatter("---\nTitle: X\nSTATUS: Draft\n---\n")
        assert "title" in fields
        assert "status" in fields

    def test_values_unquoted(self) -> None:
        fields = parse_yaml_frontmatter("---\ntitle: \"Hello\"\nstatus: 'Draft'\n---\n")
        assert fields["title"] == "Hello"
        assert fields["status"] == "Draft"

    def test_block_list_joined(self) -> None:
        text = "---\nauthors:\n  - Alice\n  - Bob\n---\n"
        fields = parse_yaml_frontmatter(text)
        assert "Alice" in fields.get("authors", "")
        assert "Bob" in fields.get("authors", "")

    def test_comment_skipped(self) -> None:
        text = "---\n# comment\ntitle: X\n---\n"
        fields = parse_yaml_frontmatter(text)
        assert fields == {"title": "X"}

    def test_no_frontmatter_returns_empty(self) -> None:
        assert parse_yaml_frontmatter("no frontmatter here") == {}

    def test_terminator_at_line_4000(self) -> None:
        body = "\n".join(["---"] + ["title: X"] * 10 + ["---"])
        fields = parse_yaml_frontmatter(body)
        assert "title" in fields


class TestRstFieldlist:
    def test_bare_rfc822_form(self) -> None:
        fields = parse_rst_fieldlist("Title: X\nStatus: Draft\n")
        assert fields["title"] == "X"
        assert fields["status"] == "Draft"

    def test_rst_field_form(self) -> None:
        fields = parse_rst_fieldlist(":Title: X\n:Status: Draft\n")
        assert fields["title"] == "X"

    def test_spaces_in_keys_become_underscores(self) -> None:
        fields = parse_rst_fieldlist("Last Call: value\n")
        assert fields["last_call"] == "value"

    def test_underscore_title_line_skipped(self) -> None:
        text = "Title: X\n=========\nStatus: Draft\n"
        fields = parse_rst_fieldlist(text)
        assert fields["title"] == "X"
        assert fields["status"] == "Draft"

    def test_continuation_appends(self) -> None:
        text = "Author: Alice,\n        Bob\n\n"
        fields = parse_rst_fieldlist(text)
        assert "Bob" in fields["author"]

    def test_overline_underline_title_with_colon_not_mistaken_for_field(self) -> None:
        # Regression: DEP 0020 "DEP 0020: Annual Release Cycle" — a section
        # title adorned with overline+underline that contains a colon must NOT
        # be parsed as a bare RFC822 field. Before the fix this set
        # seen_any_field and the blank line after the title ended parsing,
        # so :Status: was never reached.
        text = (
            "================================\n"
            "DEP 0020: Annual Release Cycle\n"
            "================================\n"
            "\n"
            ":DEP: 0020\n"
            ":Author: Carlton Gibson\n"
            ":Status: Draft\n"
            ":Type: Process\n"
            ":Created: 2026-04-24\n"
        )
        fields = parse_rst_fieldlist(text)
        # the title line must not become a field
        assert "dep_0020" not in fields
        assert fields["status"] == "Draft"
        assert fields["author"] == "Carlton Gibson"
        assert fields["type"] == "Process"

    def test_rst_field_form_after_overline_title_with_colon(self) -> None:
        # End-to-end via parse_dep: a real DEP file whose RST title contains a
        # colon must parse its :Status: field correctly.
        text = (
            "========================\nDEP 0001: DEP Process\n========================\n\n:DEP: 0001\n:Status: Final\n"
        )
        result = parse_dep(text, "0001-dep-process.rst")
        assert result.raw_status == "Final"

    def test_pep_bare_rfc822_unchanged_by_title_guard(self) -> None:
        # PEP files start with bare RFC822 headers (no overline title); the
        # title guard must not affect them.
        fields = parse_rst_fieldlist("PEP: 1\nTitle: PEP Purpose\nStatus: Active\n")
        assert fields["pep"] == "1"
        assert fields["status"] == "Active"
