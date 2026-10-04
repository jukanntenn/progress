"""Kuma push verdict path (spec: availability monitoring): real localhost HTTP."""

from __future__ import annotations

from typing import Any

from aiohttp import test_utils, web

from progress.runtime.scheduled_run import build_kuma_push_url, push_run_verdict


class _Recorder:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[dict[str, Any]] = []

    async def handle(self, request: web.Request) -> web.Response:
        self.requests.append(
            {
                "path": request.path,
                "query": dict(request.query),
            }
        )
        return web.Response(status=self.status)


async def _serve(recorder: _Recorder) -> test_utils.TestServer:
    app = web.Application()
    app.router.add_route("*", "/api/push/{key}", recorder.handle)
    return test_utils.TestServer(app)


async def test_push_verdict_round_trip():
    recorder = _Recorder()
    server = await _serve(recorder)
    async with server:
        base = str(server.make_url("/api/push/test-key"))
        ok = await push_run_verdict(base, success=True, message="run ok", retention=2400)
        assert ok is True
        (request,) = recorder.requests
        assert request["query"]["status"] == "up"
        assert request["query"]["msg"] == "run ok"
        assert request["query"]["ping"] == "2400"


async def test_push_down_verdict():
    recorder = _Recorder()
    server = await _serve(recorder)
    async with server:
        base = str(server.make_url("/api/push/test-key"))
        ok = await push_run_verdict(base, success=False, message="boom", retention=60)
        assert ok is True
        (request,) = recorder.requests
        assert request["query"]["status"] == "down"


async def test_push_server_error_is_non_fatal():
    recorder = _Recorder(status=500)
    server = await _serve(recorder)
    async with server:
        base = str(server.make_url("/api/push/test-key"))
        ok = await push_run_verdict(base, success=True, message="x", retention=60)
        assert ok is False  # reported as not-delivered, never raised


async def test_push_unreachable_is_non_fatal():
    ok = await push_run_verdict("http://127.0.0.1:1/api/push/none", success=True, message="x", retention=60)
    assert ok is False


async def test_url_builder_matches_pushed_params():
    url = build_kuma_push_url("http://k/api/push/k", success=True, message="a b&c", retention=30)
    assert "msg=a+b%26c" in url
