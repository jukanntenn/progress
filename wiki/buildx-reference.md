# Docker Buildx Reference for Progress

## Overview

Progress uses `docker buildx` to build multi-architecture Docker images for `linux/amd64` and `linux/arm64` from a single host. Cross-platform builds rely on QEMU user-mode emulation via `binfmt_misc`.

## Buildx Basics

`docker buildx` is a Docker CLI plugin that extends `docker build` with advanced features:

- **Multi-platform builds** — build images for multiple architectures in a single invocation
- **Build cache backends** — store/retrieve cache layers in a registry or local directory
- **Multiple builders** — isolated build environments with different drivers

### Builder Drivers

| Driver | Use Case | Cache | Multi-Platform |
|--------|----------|-------|----------------|
| `docker-container` | Default for multi-platform builds | Supports all cache backends | Yes (via QEMU) |
| `docker` | Uses the built-in Docker builder | Local cache only | No (single platform only) |
| `remote` | Connect to a remote builder | Supports all cache backends | Depends on remote |

For Progress, the `docker-container` driver is required because we need multi-platform support.

### Creating a Builder

```bash
# List existing builders
docker buildx ls

# Create a multi-platform builder
docker buildx create --name progress --use

# Bootstrap the builder (starts the buildkit container)
docker buildx inspect --bootstrap
```

## Multi-Platform Builds

### How It Works

When you run a multi-platform build, buildx:

1. Creates separate build environments for each target platform
2. Uses QEMU to emulate foreign architectures (e.g., arm64 on an amd64 host)
3. Builds each platform's image independently
4. Creates a multi-architecture manifest list

### QEMU Setup

QEMU user-mode emulation must be registered with the Linux kernel's `binfmt_misc` facility:

```bash
# Register QEMU for arm64
docker run --rm --privileged tonistiigi/binfmt --install arm64

# Verify registration
ls /proc/sys/fs/binfmt_misc/qemu-aarch64
```

**Important**: QEMU emulation is significantly slower than native builds (10-100x). For frequent arm64 builds, consider setting up a native arm64 builder node.

### Platform Selection

Use `--platform` to control which platforms to build:

```bash
# Single platform (fast, no QEMU overhead for foreign arch)
docker buildx build --platform linux/amd64 ...

# Multi-platform (triggers QEMU for foreign archs)
docker buildx build --platform linux/amd64,linux/arm64 ...
```

### Load vs Push

- `--load` — loads the built image into the local Docker daemon. **Only supports single platform**. Multi-platform builds require `--push`.
- `--push` — pushes a multi-architecture manifest to a registry. Supports all selected platforms.

## Build Cache

### Registry Cache

Registry-based cache stores build cache layers in a container registry alongside your images. This is the recommended approach for Progress.

```bash
# Build with cache
docker buildx build \
  --cache-from type=registry,ref=192.168.5.50:5000/progress:cache \
  --cache-to type=registry,ref=192.168.5.50:5000/progress:cache,mode=max \
  --push \
  --platform linux/amd64,linux/arm64 \
  -t 192.168.5.50:5000/progress:latest \
  -f docker/Dockerfile .
```

#### Cache Modes

- `mode=min` (default) — only caches the final image layers. Good for `--load` builds.
- `mode=max` — caches all intermediate layers including build stages. **Recommended for multi-stage builds** because it allows reusing intermediate stages (e.g., the dependency install step).

#### Cache Scope

By default, cache is scoped per-platform. Each architecture gets its own cache blob. This prevents cross-contamination when build steps produce architecture-specific outputs.

### Cache Invalidation

Docker's cache is invalidated at the layer where a change occurs and all subsequent layers. Layer ordering in the Dockerfile is critical:

```dockerfile
# GOOD: dependencies cached separately from source code
COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --no-emit-project -o requirements.txt && \
    uv pip install --system -r requirements.txt
COPY src/ ./src/
RUN uv pip install --system --no-deps .

# BAD: any source change invalidates the dependency installation
COPY . .
RUN uv pip install --system .
```

### Build Cache Mounts

The Dockerfile uses `--mount=type=cache` to persist uv's download cache across builds:

```dockerfile
RUN --mount=type=cache,target=/root/.cache/uv \
    uv export --no-dev --no-emit-project -o /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt
```

This means even when a Docker layer is invalidated, packages are already in the cache and don't need re-downloading.

### No-Cache Builds

```bash
docker buildx build --no-cache ...
```

Bypasses all cache. Use for debugging or when cache is corrupted.

## Common Issues

### "no builder found" or "builder does not support platform"

Create and use a `docker-container` driver builder:

```bash
docker buildx create --name progress --use
docker buildx inspect --bootstrap
```

### QEMU not registered

```bash
docker run --rm --privileged tonistiigi/binfmt --install arm64
```

### Cache not being used

- Ensure `--cache-from` and `--cache-to` use the same reference
- Use `mode=max` in `--cache-to` for multi-stage builds
- Check that the registry supports manifest lists (most modern registries do)

### Slow cross-platform builds

This is inherent to QEMU emulation. Mitigations:

1. Use `--platform` to build only the platform you need
2. Ensure dependency installation is properly cached (separate COPY layer)
3. Use `mode=max` cache to reuse intermediate layers
4. Consider a native arm64 builder node for frequent builds
