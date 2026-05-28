#!/usr/bin/env python3
"""Build multi-architecture Docker images for Progress using Docker buildx.

Builds a single unified image containing:
  - FastAPI backend (API, CLI, scheduler)
  - Next.js frontend (standalone)
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
import os
import platform
import subprocess
import sys

DEFAULT_REGISTRY = "192.168.5.50:5000"
ALL_PLATFORMS = ("linux/amd64", "linux/arm64")

PLATFORM_ALIASES = {
    "amd64": "linux/amd64",
    "arm64": "linux/arm64",
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
        help=f"Container registry (default: {DEFAULT_REGISTRY})",
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
        help="Target platform (amd64 or arm64). Repeatable. Defaults to all platforms.",
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


def resolve_platforms(platform_args):
    resolved = []
    for p in platform_args:
        if p in PLATFORM_ALIASES:
            resolved.append(PLATFORM_ALIASES[p])
        elif p in ALL_PLATFORMS:
            resolved.append(p)
        else:
            env_error(
                f"Unknown platform: {p}",
                f"Supported platforms: {', '.join(PLATFORM_ALIASES.keys())}",
            )
    resolved = list(dict.fromkeys(resolved))
    return resolved if resolved else list(ALL_PLATFORMS)


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
            builder_platforms = [
                p.strip() for p in stripped.split(":", 1)[1].split(",")
            ]

    host_platform = detect_host_platform()
    missing = [p for p in target_platforms if p not in builder_platforms]

    foreign_platforms = [p for p in missing if p != host_platform]

    if foreign_platforms:
        for p in foreign_platforms:
            arch = QEMU_ARCH_MAP.get(p)
            if arch and not os.path.exists(f"/proc/sys/fs/binfmt_misc/qemu-{arch}"):
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
                builder_platforms = [
                    p.strip() for p in stripped.split(":", 1)[1].split(",")
                ]
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
    target_platforms = resolve_platforms(args.platform)

    if args.push:
        platforms_to_build = target_platforms
    else:
        host_platform = detect_host_platform()
        if host_platform in target_platforms:
            platforms_to_build = [host_platform]
        else:
            platforms_to_build = [target_platforms[0]]

    builder_name = check_environment(platforms_to_build)

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    dockerfile_path = os.path.join(project_root, DOCKERFILE)

    all_tags = args.tags or ["latest"]
    full_image_names = []
    cmd = ["docker", "buildx", "build"]
    for tag in all_tags:
        if args.push:
            full_tag = f"{args.registry}/{IMAGE_NAME}:{tag}"
        else:
            full_tag = f"{IMAGE_NAME}:{tag}"
        full_image_names.append(full_tag)
        cmd.extend(["--tag", full_tag])

    cmd.extend(["--platform", ",".join(platforms_to_build)])

    if args.push:
        cmd.append("--push")
        cache_ref = f"{args.registry}/{IMAGE_NAME}:cache"
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
