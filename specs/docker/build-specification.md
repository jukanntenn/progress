# Docker Build Specification

## Base Images

| Image | Stage | Version | Size (compressed) |
|-------|-------|---------|-------------------|
| `python:3.13-alpine` | Python deps + runtime | Pinned to Alpine | ~50MB |
| `node:22-alpine` | Node deps + build | Pinned to Alpine | ~60MB |

All base images use Alpine Linux for minimal size.

## Build Tool

**docker buildx** — Docker CLI plugin for multi-platform and cache-enabled builds.

Key features used:
- Multi-platform builds via QEMU emulation (`docker-container` driver)
- Registry-based build cache (`--cache-to`/`--cache-from`)
- Multi-stage Dockerfile builds
- Build cache mounts (`--mount=type=cache`)

## Directory Structure

```
progress/
├── docker/                          # Production image building
│   ├── build.py                     # Build script (environment check + buildx invocation)
│   ├── Dockerfile                   # Unified multi-stage image (backend + frontend + proxy)
│   ├── docker-compose.yml           # Runtime compose configuration
│   ├── Caddyfile                    # Caddy reverse proxy routing rules
│   └── s6/                          # s6-overlay process manager configuration
│       ├── cont-init.d/             # Container initialization scripts
│       └── s6-rc.d/                 # Service definitions (fastapi, nextjs, caddy, cron)
├── .dockerignore                    # Excludes tests, specs, guides, wiki from build context
├── pyproject.toml                   # Project dependencies
├── uv.lock                          # Locked dependency versions
└── src/                             # Source code
    └── progress/
        ├── api/                     # FastAPI backend
        ├── locales/                 # i18n translation files (.po → .mo compilation)
        └── ...                      # Backend Python modules
```

## Optimization Mechanisms

### Layer Cache Ordering

Dependencies are installed before source code is copied. This ensures that code changes don't invalidate the expensive dependency installation layer.

**Python deps stage:**
1. `COPY pyproject.toml uv.lock` → `RUN uv export ... | uv pip install --system -r ...` — cached unless dependencies change
2. `COPY src/` — invalidated by Python source changes
3. `RUN uv pip install --system --no-deps .` — only re-runs after source changes

**Node deps stage:**
1. `COPY package.json pnpm-lock.yaml pnpm-workspace.yaml` → `RUN pnpm install --frozen-lockfile` — cached unless dependencies change

**Node build stage:**
1. `COPY --from=node-deps /app/node_modules` — cached from deps stage
2. `COPY web/` — invalidated by frontend source changes
3. `RUN next build` — only re-runs after frontend changes

### Two-Step Dependency Installation (Python)

The builder stage separates dependency installation from project installation:

1. `uv export --no-dev --no-emit-project` generates a requirements file containing only third-party dependencies
2. `uv pip install --system -r requirements.txt` installs all dependencies
3. After copying source code, `uv pip install --system --no-deps .` installs only the project package

This means source code changes never invalidate the dependency installation layer.

### Build Cache Mounts

The Dockerfile uses `--mount=type=cache,target=/root/.cache/uv` to persist uv's download cache across builds. Even when a layer is invalidated, packages are already cached locally and don't need re-downloading.

### Alpine Base Images

Alpine Linux base images minimize image size (~5MB base vs ~80MB for Debian slim). Runtime dependencies are installed via `apk add --no-cache`.

### Corepack (Frontend)

pnpm is activated via `corepack enable` instead of `npm install -g pnpm`. The exact pnpm version is pinned in `package.json`'s `packageManager` field, ensuring reproducible builds.

### Next.js Standalone Output

`next.config.ts` sets `output: "standalone"`, which produces a minimal server bundle without the full `node_modules`. The standalone output is copied to the runtime image.

### Build Context Filtering

The root `.dockerignore` excludes non-essential files from the build context:
- Development files: `.venv/`, `.claude/`, `.pytest_cache/`, `.ruff_cache/`
- Non-code directories: `tests/`, `specs/`, `guides/`, `wiki/`, `devops/`, `scripts/`, `data/`
- Generated files: `__pycache__/`, `node_modules/`, `*.db`, `*.log`
- Configuration: `config*.toml`, `requirements.txt`

### Registry-Based Build Cache

When pushing images (`--push`), build cache is stored in the same registry using `--cache-to`/`--cache-from` with `mode=max`. Cache is scoped per-platform to avoid cross-contamination between architecture-specific build outputs.

Cache reference pattern: `192.168.5.50:5000/progress:cache`.

## Build Script (`docker/build.py`)

### Behavior

The script performs two functions in order:

1. **Environment inspection** — verifies all requirements are met before building
2. **Image build** — invokes `docker buildx build` with the correct arguments

The script does **not** modify the environment. If requirements are not met, it exits with an error and instructions for manual resolution.

### Environment Checks

| Check | Command | Failure |
|-------|---------|---------|
| Docker daemon running | `docker info` | Exit 2 |
| buildx plugin available | `docker buildx version` | Exit 2 |
| Builder supports target platforms | `docker buildx inspect` | Exit 2 |
| QEMU registered for foreign architectures | `/proc/sys/fs/binfmt_misc/qemu-<arch>` | Exit 2 |

### CLI Flags

| Flag | Description | Default |
|------|-------------|---------|
| `--push` | Push to registry (multi-platform) | Load locally (single platform) |
| `--registry` | Container registry address | `192.168.5.50:5000` |
| `--tags` | Image tags | `latest` |
| `--platform` | Target platform(s): `amd64`, `arm64`. Repeatable. | Both platforms |
| `--no-cache` | Disable all build cache | Cache enabled |
| `--verbose` | Full build output (no progress bar) | Compact progress |

### Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Build failure (buildx command failed) |
| 2 | Environment check failure (missing tool, unregistered QEMU, unsupported platform) |
| 3 | Invalid arguments |

### Error Output Format

All environment errors follow this format:

```
ERROR: <description of the problem>
HINT: <command or action to resolve>
AGENT: Stop all subsequent actions. Report this error to the user. Do not attempt to resolve automatically.
```

## Build Workflows

### Normal Flow: Build and Load Locally

```bash
# Build for the host platform
python3 docker/build.py

# Build only arm64
python3 docker/build.py --platform arm64

# Build with verbose output
python3 docker/build.py --verbose

# Build with a custom tag
python3 docker/build.py --tags v1.0.0
```

1. Script checks environment (Docker daemon, buildx, builder)
2. Resolves target platforms (single host platform for `--load`)
3. Runs `docker buildx build --load`
4. Image available locally as `progress:latest`

### Normal Flow: Build and Push to Registry

```bash
# Push both platforms to default registry
python3 docker/build.py --push

# Push arm64 only with additional tags
python3 docker/build.py --push --platform arm64 --tags v1.0.0 latest
```

1. Script checks environment (Docker daemon, buildx, builder, QEMU)
2. Resolves target platforms (all specified platforms for `--push`)
3. Runs `docker buildx build --push` with `--cache-from`/`--cache-to`
4. Image pushed to registry with multi-architecture manifest

### Abnormal Flow: Environment Failure

```bash
$ python3 docker/build.py --push --platform arm64
ERROR: QEMU binfmt for aarch64 is not registered — required for cross-platform build (linux/arm64).
HINT: Run: docker run --rm --privileged tonistiigi/binfmt --install arm64
AGENT: Stop all subsequent actions. Report this error to the user. Do not attempt to resolve automatically.
```

The script exits with code 2. No build is attempted. The user (or AI agent) must resolve the environment issue before retrying.

### Abnormal Flow: Build Failure

```bash
$ python3 docker/build.py
ERROR: Build failed (exit code 1)!
```

The script exits with code 1. The buildx error output is visible in stderr. The user should inspect the output for compilation or dependency errors.
