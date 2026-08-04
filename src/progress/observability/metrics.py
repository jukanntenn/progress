"""Business metrics + ``@observed`` decorator (spec 04).

``@observed`` wraps an async function in an OTel span and records:

* a duration histogram ``<name>.duration``
* a failure counter ``<name>.failures``

It replaces the prior ``record_analysis`` / ``record_analysis_failure``
double-counting trap (spec 04 deletion list).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import functools
import logging
from time import perf_counter
from typing import Any, TypeVar

from opentelemetry import metrics, trace

_logger = logging.getLogger(__name__)

T = TypeVar("T")

_meter: metrics.Meter | None = None
_duration_histograms: dict[str, metrics.Counter | metrics.Histogram] = {}
_failure_counters: dict[str, metrics.Counter] = {}
_event_counters: dict[str, metrics.Counter] = {}


def _get_meter() -> metrics.Meter:
    global _meter
    if _meter is None:
        _meter = metrics.get_meter("progress")
    return _meter


def _duration_histogram(name: str) -> metrics.Histogram:
    if name not in _duration_histograms:
        _duration_histograms[name] = _get_meter().create_histogram(
            name=f"{name}.duration",
            unit="s",
            description=f"Duration of {name}",
        )
    return _duration_histograms[name]  # ty:ignore[invalid-return-type]


def _failure_counter(name: str) -> metrics.Counter:
    if name not in _failure_counters:
        _failure_counters[name] = _get_meter().create_counter(
            name=f"{name}.failures",
            description=f"Failure count of {name}",
        )
    return _failure_counters[name]


def observed(
    name: str,
    *,
    attributes: dict[str, str] | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorate an async function to record span + duration histogram + failures."""

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        tracer = trace.get_tracer("progress")

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attrs = dict(attributes or {})
            start = perf_counter()
            with tracer.start_as_current_span(name, attributes=attrs) as span:
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    _failure_counter(name).add(1, attrs)
                    raise
                finally:
                    _duration_histogram(name).record(perf_counter() - start, attrs)

        return wrapper

    return decorator


@asynccontextmanager
async def observe_span(name: str, *, attributes: dict[str, str] | None = None) -> AsyncIterator[None]:
    """Async context manager form of ``@observed`` for inline use."""
    tracer = trace.get_tracer("progress")
    attrs = dict(attributes or {})
    start = perf_counter()
    with tracer.start_as_current_span(name, attributes=attrs) as span:
        try:
            yield
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
            _failure_counter(name).add(1, attrs)
            raise
        finally:
            _duration_histogram(name).record(perf_counter() - start, attrs)


def record_business_event(name: str, *, value: float = 1, attributes: dict[str, str] | None = None) -> None:
    """Record a discrete business event as a counter increment.

    Uses a dedicated counter registry separate from ``_failure_counters`` so
    failure metrics (``<name>.failures``) and business event metrics never
    share state — avoiding the double-counting trap spec 04 calls out.
    """
    attrs = dict(attributes or {})
    counter = _event_counters.get(name)
    if counter is None:
        counter = _get_meter().create_counter(
            name=name,
            description=f"Business event: {name}",
        )
        _event_counters[name] = counter
    counter.add(value, attrs)


__all__ = ["observe_span", "observed", "record_business_event"]
