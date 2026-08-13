"""Unit tests for v2ex source-key encoding (spec v2ex §4)."""

from __future__ import annotations

from progress.integrations.v2ex.fetcher import parse_source, source_key


class TestSourceKey:
    def test_tab_encoded(self) -> None:
        assert source_key("jobs") == "tab:jobs"
        assert source_key("creative") == "tab:creative"

    def test_round_trip(self) -> None:
        for tab in ("jobs", "creative", "tech", "r2"):
            assert parse_source(source_key(tab)) == tab

    def test_unknown_prefix_returned_as_is(self) -> None:
        # future node:/member: sources must not break the parser
        assert parse_source("node:rust") == "node:rust"
        assert parse_source("member:alice") == "member:alice"
