"""Unit tests for ``progress.utils.http`` retry helpers (spec 07)."""

from __future__ import annotations

import aiohttp
import pytest

from progress.errors import ExternalServiceException
from progress.utils.http import retry_async


class TestRetryAsyncSuccessPath:
    async def test_returns_result_on_first_success(self) -> None:
        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await retry_async(func, retries=3, initial_delay=0, max_delay=0)
        assert result == "ok"
        assert call_count == 1

    async def test_passes_args_and_kwargs(self) -> None:
        async def func(a: int, *, b: int) -> int:
            return a + b

        result = await retry_async(func, 1, b=2, retries=1, initial_delay=0, max_delay=0)
        assert result == 3


class TestRetryAsyncRetriesOnMatchingException:
    async def test_retries_on_external_service_exception_then_succeeds(self) -> None:
        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ExternalServiceException("transient")
            return "recovered"

        result = await retry_async(func, retries=3, initial_delay=0, max_delay=0, retry_on=ExternalServiceException)
        assert result == "recovered"
        assert call_count == 3

    async def test_retries_on_aiohttp_client_error(self) -> None:
        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise aiohttp.ClientError("connection reset")
            return "ok"

        result = await retry_async(func, retries=3, initial_delay=0, max_delay=0, retry_on=aiohttp.ClientError)
        assert result == "ok"
        assert call_count == 2


class TestRetryAsyncDoesNotRetryNonMatching:
    async def test_raises_immediately_on_unmatched_exception(self) -> None:
        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await retry_async(func, retries=3, initial_delay=0, max_delay=0, retry_on=ExternalServiceException)
        assert call_count == 1


class TestRetryAsyncExhaustion:
    async def test_raises_original_exception_when_exhausted(self) -> None:
        """With reraise=True the original exception propagates, not RetryError."""
        call_count = 0

        async def func() -> str:
            nonlocal call_count
            call_count += 1
            raise ExternalServiceException("always fails")

        with pytest.raises(ExternalServiceException, match="always fails"):
            await retry_async(func, retries=3, initial_delay=0, max_delay=0, retry_on=ExternalServiceException)
        assert call_count == 3
