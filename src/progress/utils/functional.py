"""Functional helpers: decorators and retry logic."""

import asyncio
import logging
import time
from collections.abc import Callable
from functools import wraps
from typing import Any, Literal

logger = logging.getLogger(__name__)

BackoffStrategy = Literal["exponential", "fixed"]


def retry(
    times: int,
    initial_delay: float = 1.0,
    backoff: BackoffStrategy = "exponential",
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[tuple[Any, ...], dict[str, Any], Exception, int], None] | None = None,
    max_delay: float | None = None,
):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay

            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    is_last_attempt = attempt == times - 1
                    error_msg = str(e)[:100]

                    if is_last_attempt:
                        logger.warning(f"Command failed, max retries ({times}) reached")
                        raise

                    logger.warning(
                        f"Command failed (attempt {attempt + 1}/{times}), "
                        f"retrying in {delay}s. Error: {error_msg}"
                    )

                    if on_retry:
                        on_retry(args, kwargs, e, attempt + 1)

                    time.sleep(delay)

                    if backoff == "exponential":
                        delay *= 2
                        if max_delay is not None:
                            delay = min(delay, max_delay)

        return wrapper

    return decorator


def aretry(
    times: int,
    initial_delay: float = 1.0,
    backoff: BackoffStrategy = "exponential",
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[tuple[Any, ...], dict[str, Any], Exception, int], None] | None = None,
    max_delay: float | None = None,
):
    """Async counterpart of :func:`retry`: uses ``asyncio.sleep`` so the event
    loop is never blocked between attempts."""

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            delay = initial_delay

            for attempt in range(times):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    is_last_attempt = attempt == times - 1
                    error_msg = str(e)[:100]

                    if is_last_attempt:
                        logger.warning(f"Command failed, max retries ({times}) reached")
                        raise

                    logger.warning(
                        f"Command failed (attempt {attempt + 1}/{times}), "
                        f"retrying in {delay}s. Error: {error_msg}"
                    )

                    if on_retry:
                        on_retry(args, kwargs, e, attempt + 1)

                    await asyncio.sleep(delay)

                    if backoff == "exponential":
                        delay *= 2
                        if max_delay is not None:
                            delay = min(delay, max_delay)

        return wrapper

    return decorator
