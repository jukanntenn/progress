"""feed e2e docker lifecycle + test-data helpers (spec feed §15.3/§15.4).

This module manages the real Miniflux + PostgreSQL containers (spec feed §15.2)
and provides helpers to populate Miniflux with feeds + unread entries via its
REST API. It is the intentional docker exception to spec 15 §1.2 (see the
docker-compose.yml header comment for rationale).

The session-scoped ``miniflux_service`` fixture is idempotent: ``up`` is skipped
if the container is already running; ``down -v`` always clears the volume on
teardown (mirroring the feeber e2e harness).
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path
import subprocess
import time
from typing import TYPE_CHECKING, Any

import miniflux
import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_COMPOSE_FILE = Path(__file__).resolve().parent / "docker-compose.yml"
_BASE_URL = "http://localhost:18080"
_ADMIN_USER = "admin"
_ADMIN_PASS = "password"
_API_KEY_DESCRIPTION = "e2e-test-key"
_HEALTH_TIMEOUT = 180


def _run_compose(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose", "-f", str(_COMPOSE_FILE), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _parse_compose_ps(output: str) -> dict[str, dict[str, Any]]:
    """Parse ``docker compose ps --format json`` output.

    Docker Compose v2.24+ emits newline-delimited JSON (one object per line);
    older versions emit a single JSON array.  Normalise both into a dict keyed
    by ``Service`` name.
    """
    stripped = output.strip()
    if not stripped:
        return {}
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        data = None
    if isinstance(data, list):
        return {item.get("Service", ""): item for item in data if isinstance(item, dict)}
    if isinstance(data, dict):
        svc = data.get("services")
        if isinstance(svc, dict):
            return svc
    services: dict[str, dict[str, Any]] = {}
    for raw_line in stripped.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            services[item.get("Service", "")] = item
    return services


def _miniflux_healthy() -> bool:
    result = _run_compose("ps", "--format", "json", check=False)
    if result.returncode != 0:
        return False
    services = _parse_compose_ps(result.stdout or "")
    miniflux = services.get("miniflux")
    if not isinstance(miniflux, dict):
        return False
    health = (miniflux.get("Health") or "").lower()
    state = (miniflux.get("State") or "").lower()
    return health == "healthy" or state == "running"


def _wait_healthy() -> bool:
    deadline = time.monotonic() + _HEALTH_TIMEOUT
    while time.monotonic() < deadline:
        if _miniflux_healthy():
            return True
        time.sleep(2)
    return _miniflux_healthy()


def _get_or_create_api_key() -> str:

    deadline = time.monotonic() + 30
    last_exc: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client = miniflux.Client(_BASE_URL, username=_ADMIN_USER, password=_ADMIN_PASS)
            for key in client.get_api_keys():
                if key.get("description") == _API_KEY_DESCRIPTION:
                    return str(key["token"])
            new_key = client.create_api_key(_API_KEY_DESCRIPTION)
            return str(new_key["token"])
        except Exception as e:
            last_exc = e
            time.sleep(2)
    raise RuntimeError(f"miniflux API not ready after retries: {last_exc}")


def _is_running() -> bool:
    return _miniflux_healthy()


@pytest.fixture(scope="session")
def miniflux_service() -> Iterator[tuple[str, str]]:
    """Start Miniflux + PG; yield ``(base_url, api_key)``; tear down on exit.

    Idempotent: if the containers are already up (e.g. re-running e2e locally)
    the ``up`` is skipped so the fixture stays cheap. ``down -v`` always clears
    the volume on teardown so the next session starts clean.
    """
    if not _is_running():
        _run_compose("up", "-d")
    if not _wait_healthy():
        _run_compose("logs", "miniflux", check=False)
        raise RuntimeError("miniflux did not become healthy within timeout")
    api_key = _get_or_create_api_key()
    try:
        yield _BASE_URL, api_key
    finally:
        _run_compose("down", "-v", check=False)


def _admin_client() -> Any:

    return miniflux.Client(_BASE_URL, username=_ADMIN_USER, password=_ADMIN_PASS)


def clear_all_data() -> None:
    """Delete all feeds + non-Uncategorized categories (spec feed §15.4)."""
    client = _admin_client()
    for feed in client.get_feeds():
        try:
            client.delete_feed(feed["id"])
        except Exception as e:  # pragma: no cover - best-effort cleanup
            logger.debug("delete feed %s failed: %s", feed.get("id"), e)
    for category in client.get_categories():
        if str(category.get("title", "")).lower() != "uncategorized":
            try:
                client.delete_category(category["id"])
            except Exception as e:  # pragma: no cover - best-effort cleanup
                logger.debug("delete category %s failed: %s", category.get("id"), e)


def _create_category(name: str) -> int:
    return int(_admin_client().create_category(name)["id"])


def create_feed_with_entries(
    *,
    name: str,
    count: int,
    content_len: int = 200,
    base_entry_id: int = 1,
) -> int:
    """Create a feed shell via OPML + inject ``count`` unread entries (§15.4).

    Idempotent: if a feed with the same ``xmlUrl`` already exists, new entries
    are injected into the existing feed instead of creating a duplicate.

    Returns the feed's Miniflux id. ``base_entry_id`` is only used to vary
    entry content/titles so runs are deterministic. Entry ids are assigned by
    Miniflux (monotonic) — callers assert on relative differences, not absolute
    ids.
    """
    client = _admin_client()
    expected_url = f"http://rss-server.invalid/{name}.xml"
    feed = next((f for f in client.get_feeds() if f.get("feed_url") == expected_url), None)
    if feed is None:
        with contextlib.suppress(Exception):
            _create_category(name)
        padding = "x" * max(0, content_len)
        opml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<opml version="2.0"><head><title>e2e</title></head><body>'
            f'<outline text="{name}" title="{name}" type="rss" '
            f'xmlUrl="{expected_url}" htmlUrl="http://example.invalid/{name}"/>'
            f"</body></opml>"
        )
        client.import_feeds(opml)
        time.sleep(1)
        feed = next((f for f in client.get_feeds() if f.get("feed_url") == expected_url), None)
        if feed is None:
            raise RuntimeError(f"OPML import did not create a feed for {name!r}")
    feed_id = int(feed["id"])
    padding = "x" * max(0, content_len)
    for i in range(count):
        client.import_entry(
            feed_id,
            url=f"http://example.invalid/{name}/{base_entry_id + i}",
            title=f"{name} entry {base_entry_id + i}",
            content=f"{name} body {base_entry_id + i}. {padding}",
            status="unread",
        )
    return feed_id


def list_feed_ids() -> list[int]:
    return [int(f["id"]) for f in _admin_client().get_feeds()]


def delete_feed(feed_id: int) -> None:
    _admin_client().delete_feed(feed_id)


__all__ = [
    "clear_all_data",
    "create_feed_with_entries",
    "delete_feed",
    "list_feed_ids",
    "miniflux_service",
]
