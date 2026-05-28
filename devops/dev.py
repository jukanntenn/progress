#!/usr/bin/env python3
"""Progress development environment manager.

Manages backend (FastAPI) and frontend (Next.js) for local development.

Usage:
    python devops/dev.py start    # Start all services (default)
    python devops/dev.py stop     # Stop all services
"""

import argparse
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_PID_FILE = SCRIPT_DIR / "backend.pid"
FRONTEND_PID_FILE = SCRIPT_DIR / "frontend.pid"
BACKEND_LOG_FILE = SCRIPT_DIR / "backend.log"
FRONTEND_LOG_FILE = SCRIPT_DIR / "frontend.log"

BACKEND_PORT = 5000
FRONTEND_PORT = 3000

logger = logging.getLogger("dev")


def setup_logging():
    handler_out = logging.StreamHandler(sys.stdout)
    handler_out.setLevel(logging.INFO)
    handler_out.addFilter(lambda record: record.levelno <= logging.INFO)

    handler_err = logging.StreamHandler(sys.stderr)
    handler_err.setLevel(logging.WARNING)

    logging.basicConfig(level=logging.INFO, handlers=[handler_out, handler_err])


def parse_args():
    parser = argparse.ArgumentParser(
        description="Progress development environment manager"
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("start", help="Start all services (default)")
    sub.add_parser("stop", help="Stop all services")
    args = parser.parse_args()
    if not args.command:
        args.command = "start"
    return args


def run(name, *args, **kwargs):
    defaults = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    defaults.update(kwargs)
    return subprocess.run([name, *args], **defaults)


def wait_for(url, name, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            result = run("curl", "-sf", url)
            if result.returncode == 0:
                logger.info("[ok] %s is ready", name)
                return True
        except Exception:
            pass
        time.sleep(2)
    logger.warning("[warn] %s not ready after %ds, continuing...", name, timeout)
    return False


def start():
    frontend_dir = PROJECT_ROOT / "web"

    logger.info("Starting backend (fastapi dev)...")
    env = os.environ.copy()
    env["CONFIG_FILE"] = str(PROJECT_ROOT / "config.toml")
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    with open(BACKEND_LOG_FILE, "w") as log:
        backend_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "fastapi",
                "dev",
                "--port",
                str(BACKEND_PORT),
            ],
            cwd=str(PROJECT_ROOT),
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=env,
        )
    BACKEND_PID_FILE.write_text(str(backend_proc.pid))

    wait_for(f"http://localhost:{BACKEND_PORT}/api/v1/reports", "Backend", timeout=30)

    if not (frontend_dir / "node_modules").exists():
        logger.info("Installing frontend dependencies...")
        run("pnpm", "install", cwd=str(frontend_dir))

    logger.info("Starting frontend (pnpm dev)...")
    with open(FRONTEND_LOG_FILE, "w") as log:
        frontend_proc = subprocess.Popen(
            ["pnpm", "dev"],
            cwd=str(frontend_dir),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    FRONTEND_PID_FILE.write_text(str(frontend_proc.pid))

    wait_for(f"http://localhost:{FRONTEND_PORT}", "Frontend", timeout=60)

    logger.info("Services:")
    logger.info("  Frontend:     http://localhost:%d", FRONTEND_PORT)
    logger.info("  Backend API:  http://localhost:%d/api/v1", BACKEND_PORT)
    logger.info("Stop: python devops/dev.py stop")


def stop():
    for pid_file, name in [
        (BACKEND_PID_FILE, "backend"),
        (FRONTEND_PID_FILE, "frontend"),
    ]:
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            try:
                os.killpg(pid, signal.SIGTERM)
                time.sleep(1)
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            pid_file.unlink()

    for port in [FRONTEND_PORT, BACKEND_PORT]:
        try:
            result = run("lsof", "-ti", f":{port}")
            if result.stdout.strip():
                for pid_str in result.stdout.strip().splitlines():
                    subprocess.run(["kill", "-9", pid_str], capture_output=True)
        except Exception:
            pass

    logger.info("All services stopped")


def main():
    setup_logging()
    args = parse_args()
    if args.command == "start":
        start()
    elif args.command == "stop":
        stop()


if __name__ == "__main__":
    main()
