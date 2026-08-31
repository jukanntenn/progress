"""Unit tests for :func:`progress.observability.report_severe`.

The helper is the single wiring point for the severe-exception policy: every
caught exception is captured to Bugsink unless the catch is provably part of
the normal business-logic chain. It must never raise, and it must stay a no-op
when Bugsink is uninitialized or unconfigured.
"""

from __future__ import annotations

from unittest.mock import patch

from progress.observability import report_severe


class TestReportSevere:
    def test_captures_exception_via_sentry(self) -> None:
        exc = ValueError("boom")
        with patch("progress.observability.sentry_sdk.capture_exception") as capture:
            report_severe(exc)
        capture.assert_called_once_with(exc)

    def test_swallows_capture_failure(self) -> None:
        with patch("progress.observability.sentry_sdk.capture_exception", side_effect=RuntimeError("sdk broken")):
            report_severe(ValueError("boom"))

    def test_noop_when_sdk_uninitialized(self) -> None:
        report_severe(ValueError("boom"))
