"""Unit tests for the proposal ``_normalize_status`` observability wrapper.

The wrapper (spec proposal §10.4 + observability hardening) emits a warning log
and a ``progress.proposal.status_unknown`` business event whenever
:func:`normalize` falls through to ``unknown``, so a silent parse failure (e.g.
the RST title-with-colon bug) is never invisible to operators.
"""

from __future__ import annotations

import logging

from progress.integrations.proposal.tracker import _normalize_status


class TestNormalizeStatusObservability:
    def test_known_status_returns_normalized_silently(self, monkeypatch) -> None:
        called: list[str] = []
        monkeypatch.setattr(
            "progress.integrations.proposal.tracker.record_business_event",
            lambda name, **kw: called.append(name),
        )
        result = _normalize_status("Draft", "dep", "0020.rst")
        assert result == "draft"
        assert called == []  # no event for a known status

    def test_unknown_status_emits_warning_and_event(self, monkeypatch, caplog) -> None:
        events = []
        monkeypatch.setattr(
            "progress.integrations.proposal.tracker.record_business_event",
            lambda name, **kw: events.append((name, kw)),
        )
        with caplog.at_level(logging.WARNING, logger="progress.integrations.proposal.tracker"):
            result = _normalize_status("", "dep", "bad.rst")
        assert result == "unknown"
        # business event recorded with diagnostic attributes
        assert len(events) == 1
        assert events[0][0] == "progress.proposal.status_unknown"
        attrs = events[0][1]["attributes"]
        assert attrs["raw_status"] == ""
        assert attrs["kind"] == "dep"
        assert attrs["file_name"] == "bad.rst"
        # warning log emitted with the same context
        assert any("normalized to unknown" in r.message for r in caplog.records)
