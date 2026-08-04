"""Unified secret scrubbing (spec 04).

A single ``scrub_secrets`` helper covers three sinks that previously each had
their own (inconsistent) redaction:

* Sentry ``before_send`` hook
* structlog event dict processor
* OTel span attributes

Recursive over dicts/lists; replaces known secret keys' values with
``[REDACTED]``. Also collapses anything that looks like a credential in a
URL (``https://user:token@host``) so embedded gh tokens don't leak.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "gh_token",
        "token",
        "password",
        "secret",
        "authorization",
        "webhook_url",
        "dsn",
        "api_key",
        "apikey",
        "api_secret",
        "access_token",
        "refresh_token",
        "client_secret",
        "private_key",
        "session_token",
    }
)

_REDACTED: str = "[REDACTED]"

_CREDENTIAL_IN_URL: re.Pattern[str] = re.compile(r"^[^/@]+@[^/@]+")


def scrub_value(value: Any) -> Any:
    """Recursively scrub a value (dict / list / scalar)."""
    if isinstance(value, dict):
        return {k: (_REDACTED if _is_secret_key(k) else scrub_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    if isinstance(value, str):
        return _scrub_url(value)
    return value


def scrub_secrets(value: Any) -> Any:
    """Public entry point; alias for :func:`scrub_value` (spec 04 naming)."""
    return scrub_value(value)


def scrub_secrets_processor(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """structlog processor form of :func:`scrub_secrets`.

    structlog processors receive ``(logger, method_name, event_dict)`` and
    must return the (possibly mutated) event dict. ``scrub_secrets`` itself
    only takes the value, so we adapt the signature here.
    """
    return scrub_value(event_dict)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _SECRET_KEYS:
        return True
    return any(secret in lowered for secret in ("token", "secret", "password", "api_key", "apikey"))


def _scrub_url(value: str) -> str:
    """Strip embedded ``user:password`` from URLs that look like credentials."""
    if "://" not in value or " " in value or "\n" in value:
        return value
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    if not parsed.scheme or not parsed.netloc:
        return value
    if not _CREDENTIAL_IN_URL.match(parsed.netloc):
        return value
    cleaned_netloc = parsed.hostname or ""
    if parsed.port:
        cleaned_netloc = f"{cleaned_netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=cleaned_netloc))


def scrub_event(event: dict[str, Any], _hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Sentry ``before_send`` compatible hook (mutates + returns event)."""
    return scrub_secrets(event)


__all__ = ["scrub_event", "scrub_secrets", "scrub_secrets_processor", "scrub_value"]
