#!/usr/bin/env python3
"""Verify a deployed Progress instance is up and running the expected build.

Waits for the readiness endpoint (``/readyz`` — app up + DB reachable), then,
when ``--sha`` is given, compares the ``git_sha`` reported by
``/api/v1/version`` against the expected commit. The sha check is the deploy
verification: a container can be up while still running the previous image.

Used by the Ansible playbook (``devops/ansible/main.yml``) after deployment and
by humans for manual verification. Pure standard library; runs on the
controller machine, not on the target host.

Exit codes:
  0 - ready (and sha matches, when required)
  1 - not ready in time, or sha mismatch
  2 - invalid arguments
"""

import argparse
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(url: str, timeout: float) -> dict[str, object] | None:
    try:
        with urlopen(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            return json.loads(resp.read())
    except (HTTPError, URLError, OSError, json.JSONDecodeError):
        return None


def wait_ready(base_url: str, interval: float, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = fetch_json(f"{base_url}/readyz", timeout=interval)
        if body and body.get("status") == "ok":
            return True
        time.sleep(interval)
    return False


def check_git_sha(base_url: str, expected: str, timeout: float) -> tuple[bool, str]:
    body = fetch_json(f"{base_url}/api/v1/version", timeout=timeout)
    if body is None:
        return False, "version endpoint unreachable"
    actual = body.get("git_sha", "unknown")
    if actual != expected:
        return False, f"git_sha mismatch: expected {expected}, running {actual}"
    return True, f"git_sha matches: {actual}"


def parse_args():
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--url", default="http://localhost:5053", help="Base URL of the deployed instance")
    parser.add_argument("--sha", help="Expected git_sha; verify the running image matches it")
    parser.add_argument("--interval", type=float, default=5.0, help="Poll interval in seconds (default: 5)")
    parser.add_argument("--timeout", type=float, default=180.0, help="Readiness timeout in seconds (default: 180)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not wait_ready(args.url, args.interval, args.timeout):
        print(f"FAIL: {args.url}/readyz never returned ok within {args.timeout:.0f}s", file=sys.stderr)
        return 1
    print(f"ready: {args.url}/readyz ok")
    if args.sha:
        ok, detail = check_git_sha(args.url, args.sha, args.timeout)
        if not ok:
            print(f"FAIL: {detail}", file=sys.stderr)
            return 1
        print(detail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
