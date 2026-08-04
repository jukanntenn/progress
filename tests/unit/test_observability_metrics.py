"""Unit tests for ``progress.observability.metrics`` (spec 04).

The business-metric helpers (``record_business_event`` / ``observe_span`` /
``@observed``) are wired into the run pipeline. Tests run with
``setup_observability`` stubbed to a no-op (conftest ``_stub_observability``),
so no real MeterProvider / TracerProvider is registered and the OTel API
hands back no-op proxy instruments. These tests pin that behaviour: the
helpers must be safe no-ops in that state — no exceptions, no emitted
records — so the run pipeline can call them unconditionally without breaking
tests.
"""

from __future__ import annotations

import pytest

from progress.observability.metrics import observe_span, observed, record_business_event


class TestNoOpInTestEnvironment:
    """No real provider registered (the test environment). The helpers must
    be safe no-ops: never raise, regardless of the underlying proxy meter."""

    def test_record_business_event_does_not_raise(self) -> None:
        record_business_event("progress.test.event", attributes={"k": "v"})
        record_business_event("progress.test.event", value=5)

    @pytest.mark.asyncio
    async def test_observe_span_does_not_raise(self) -> None:
        async with observe_span("progress.test.span", attributes={"k": "v"}):
            value = await _sample_async()
        assert value == 42

    @pytest.mark.asyncio
    async def test_observed_decorator_returns_value(self) -> None:
        @observed("progress.test.observed", attributes={"k": "v"})
        async def adder(a: int, b: int) -> int:
            return a + b

        assert await adder(2, 3) == 5

    @pytest.mark.asyncio
    async def test_observed_decorator_propagates_exception(self) -> None:
        @observed("progress.test.failing")
        async def boom() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await boom()

    @pytest.mark.asyncio
    async def test_observe_span_propagates_exception(self) -> None:
        with pytest.raises(ValueError, match="boom"):
            async with observe_span("progress.test.span"):
                raise ValueError("boom")


async def _sample_async() -> int:
    return 42
