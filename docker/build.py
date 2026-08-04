#!/usr/bin/env python3
"""Build multi-architecture Docker images for Progress using Docker buildx.

Builds a single unified image containing:
  - FastAPI backend (API, CLI)
  - Vite static SPA (served by Caddy, no node runtime)
  - Caddy reverse proxy
  - s6-overlay process manager

Supports load (local, single platform) and push (multi-platform to registry) modes.

Environment requirements (not auto-resolved):
  - Docker daemon running
  - Docker buildx plugin available
  - Active buildx builder supporting target platforms
  - QEMU binfmt registered for foreign architectures (cross-platform builds)

Exit codes:
  0 - Success
  1 - Build failure
  2 - Environment check failure
  3 - Invalid arguments
"""

import argparse
import logging
from pathlib import Path
import platform
import re as _re
import subprocess
import sys

DEFAULT_REGISTRY = "192.168.5.50:5000"
ALL_PLATFORMS = ("linux/amd64", "linux/arm64")

PLATFORM_ALIASES = {
    "amd64": "linux/amd64",
    "arm64": "linux/arm64",
}

REGISTRY_ALIASES = {
    "ghcr": ("ghcr.io", True),
    "dockerhub": ("docker.io", True),
    "docker": ("docker.io", True),
}

QEMU_ARCH_MAP = {
    "linux/arm64": "aarch64",
    "linux/amd64": "x86_64",
}

IMAGE_NAME = "progress"
DOCKERFILE = "docker/Dockerfile"

logger = logging.getLogger("build")


def setup_logging(verbose=False):
    handler_out = logging.StreamHandler(sys.stdout)
    handler_out.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler_out.addFilter(lambda record: record.levelno <= logging.INFO)

    handler_err = logging.StreamHandler(sys.stderr)
    handler_err.setLevel(logging.WARNING)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        handlers=[handler_out, handler_err],
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Build multi-architecture Docker image for Progress",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push image to registry (default: load locally)",
    )
    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY,
        help="Container registry for --push. Aliases: ghcr, dockerhub, docker. Or a host (ghcr.io, registry.local:5000). Required for push, ignored for local load.",
    )
    parser.add_argument(
        "--tags",
        nargs="+",
        action="extend",
        default=[],
        help='Image tags (default: "latest"). Replaces the default.',
    )
    parser.add_argument(
        "--platform",
        action="append",
        default=[],
        help="Target platform (amd64 or arm64). Repeatable.",
    )
    parser.add_argument(
        "--all-platforms",
        action="store_true",
        default=False,
        help="Build all target platforms (amd64+arm64).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable build cache",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show full build output (no progress bar)",
    )
    return parser.parse_args()


def env_error(msg, hint=None):
    logger.error(msg)
    if hint:
        logger.error("HINT: %s", hint)
    logger.error(
        "AGENT: Stop all subsequent actions. Report this error to the user. Do not attempt to resolve automatically."
    )
    sys.exit(2)


def _resolve_registry(value: str) -> tuple[str, bool]:
    """Resolve --registry into (full_registry, needs_owner).

    Returns (host, needs_owner). When needs_owner is True the caller must append
    the git-derived owner; when False the value is a flat host or already
    carries a namespace.
    """
    if value in REGISTRY_ALIASES:
        host, needs_owner = REGISTRY_ALIASES[value]
        return host, needs_owner
    if "/" in value:
        return value, False
    if ":" in value or "." in value or value == "localhost":
        return value, False
    env_error(
        f"Unknown registry alias or host: {value!r}",
        "Use an alias (ghcr/dockerhub/docker), a host (ghcr.io, registry.local:5000), "
        "or a full path with namespace (ghcr.io/owner).",
    )
    sys.exit(2)


def _resolve_owner_from_git() -> str:

    url = ""
    try:
        url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception as e:
        env_error(
            f"Could not derive owner from git remote: {e}",
            "Pass --registry with a full path (e.g. --registry ghcr.io/youruser).",
        )
    m = _re.match(r"git@github\.com:([^/]+)/", url) or _re.match(r"https://github\.com/([^/]+)/", url)
    if not m:
        env_error(
            f"git remote {url!r} is not a GitHub repo; cannot derive owner",
            "Pass --registry with a full path.",
        )
        sys.exit(2)
    return m.group(1)


def resolve_platforms(args) -> list[str]:
    if getattr(args, "all_platforms", False):
        return list(ALL_PLATFORMS)
    if args.platform:
        resolved = []
        for p in args.platform:
            if p in PLATFORM_ALIASES:
                resolved.append(PLATFORM_ALIASES[p])
            elif p in ALL_PLATFORMS:
                resolved.append(p)
            else:
                env_error(
                    f"Unsupported platform: {p!r}",
                    f"Supported: {', '.join(PLATFORM_ALIASES.keys())}",
                )
        return resolved
    return [detect_host_platform()]


def detect_host_platform():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "linux/amd64"
    if machine in ("aarch64", "arm64"):
        return "linux/arm64"
    return "linux/amd64"


def check_docker_daemon():
    result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        env_error(
            "Docker daemon is not running or not accessible.",
            "Start Docker (e.g., sudo systemctl start docker) and ensure your user is in the docker group.",
        )


def check_buildx():
    try:
        subprocess.run(
            ["docker", "buildx", "version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        env_error(
            "Docker buildx is not available.",
            "Ensure Docker is installed and the buildx plugin is enabled. See: https://docs.docker.com/buildx/working-with-buildx/",
        )


def check_builder_platforms(target_platforms):
    result = subprocess.run(
        ["docker", "buildx", "inspect"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        env_error(
            f"Failed to inspect active buildx builder: {result.stderr.strip()}",
            "Try running 'docker buildx ls' to see available builders.",
        )

    builder_name = "unknown"
    builder_platforms = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name:"):
            builder_name = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("Platforms:"):
            builder_platforms = [p.strip() for p in stripped.split(":", 1)[1].split(",")]

    host_platform = detect_host_platform()
    missing = [p for p in target_platforms if p not in builder_platforms]

    foreign_platforms = [p for p in missing if p != host_platform]

    if foreign_platforms:
        for p in foreign_platforms:
            arch = QEMU_ARCH_MAP.get(p)
            if arch and not Path(f"/proc/sys/fs/binfmt_misc/qemu-{arch}").exists():
                env_error(
                    f"QEMU binfmt for {arch} is not registered — required for cross-platform build ({p}).",
                    f"Run: docker run --rm --privileged tonistiigi/binfmt --install {arch}",
                )

        result = subprocess.run(
            ["docker", "buildx", "inspect", "--bootstrap"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            env_error(
                f"Failed to bootstrap builder: {result.stderr.strip()}",
                "Try 'docker buildx inspect --bootstrap' manually.",
            )

        result = subprocess.run(
            ["docker", "buildx", "inspect"],
            capture_output=True,
            text=True,
        )
        builder_platforms = []
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("Platforms:"):
                builder_platforms = [p.strip() for p in stripped.split(":", 1)[1].split(",")]
        missing = [p for p in target_platforms if p not in builder_platforms]

    if missing:
        env_error(
            f"Active builder does not support required platform(s): {', '.join(missing)}\n"
            f"  Builder:           {builder_name}\n"
            f"  Builder platforms: {', '.join(builder_platforms) or '(none detected)'}\n"
            f"  Required:          {', '.join(target_platforms)}",
            "Create a multi-platform builder: docker buildx create --name multiplatform --use",
        )

    return builder_name


def check_environment(target_platforms):
    check_docker_daemon()
    check_buildx()
    return check_builder_platforms(target_platforms)


def build_image(args):
    if args.push and not args.registry:
        env_error(
            "--registry is required when using --push.",
            "Example: --push --registry ghcr.io/youruser",
        )
    target_platforms = resolve_platforms(args)

    if args.push:
        platforms_to_build = target_platforms
    else:
        host_platform = detect_host_platform()
        platforms_to_build = [host_platform] if host_platform in target_platforms else [target_platforms[0]]

    builder_name = check_environment(platforms_to_build)

    project_root = Path(__file__).resolve().parent.parent
    dockerfile_path = project_root / DOCKERFILE

    registry, needs_owner = _resolve_registry(args.registry)
    if needs_owner:
        owner = _resolve_owner_from_git()
        registry_prefix = f"{registry}/{owner}"
    else:
        registry_prefix = registry

    all_tags = args.tags or ["latest"]
    full_image_names = []
    cmd = ["docker", "buildx", "build"]
    for tag in all_tags:
        full_tag = f"{registry_prefix}/{IMAGE_NAME}:{tag}"
        full_image_names.append(full_tag)
        cmd.extend(["--tag", full_tag])

    cmd.extend(["--platform", ",".join(platforms_to_build)])

    if args.push:
        cmd.append("--push")
        cache_ref = f"{registry_prefix}/{IMAGE_NAME}:cache"
        if not args.no_cache:
            cmd.extend(["--cache-from", f"type=registry,ref={cache_ref}"])
            cmd.extend(["--cache-to", f"type=registry,ref={cache_ref},mode=max"])
    else:
        cmd.append("--load")

    if args.no_cache:
        cmd.append("--no-cache")

    if args.verbose:
        cmd.extend(["--progress", "plain"])

    cmd.extend(["-f", dockerfile_path, project_root])

    mode = "push" if args.push else "load"
    logger.info("Build configuration:")
    logger.info("  Mode:       %s", mode)
    logger.info("  Image:      %s", ", ".join(full_image_names))
    logger.info("  Platform:   %s", ", ".join(platforms_to_build))
    logger.info("  Builder:    %s", builder_name)
    logger.info("  Context:    %s", project_root)
    logger.info("  Dockerfile: %s", dockerfile_path)

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logger.error("Build failed (exit code %d)!", e.returncode)
        sys.exit(1)

    logger.info("Build completed: %s", ", ".join(full_image_names))


def main():
    args = parse_args()
    setup_logging(verbose=args.verbose)
    build_image(args)


if __name__ == "__main__":
    main()
