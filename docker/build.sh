#!/bin/bash
# Multi-architecture Docker image build script
# Supports: linux/amd64, linux/arm64
#
# Notes:
#   - Local builds (PUSH=false): Builds for host architecture only, loads to local Docker
#   - Remote builds (PUSH=true): Builds for all platforms in PLATFORMS, pushes to registry
#
# Usage:
#   # Build with default settings (tag: latest, registry: jukanntenn, local build for host platform)
#   ./build.sh
#
#   # Build with specific tag (will build both 0.0.1 and latest)
#   IMAGE_TAG=0.0.1 ./build.sh
#
#   # Build and push to registry (multi-architecture)
#   PUSH=true ./build.sh
#
#   # Build with custom registry
#   REGISTRY=myregistry ./build.sh
#
#   # Build with all custom options
#   IMAGE_NAME=progress IMAGE_TAG=1.0.0 REGISTRY=myregistry PUSH=true PLATFORMS=linux/amd64,linux/arm64 ./build.sh
#
# Environment Variables:
#   IMAGE_NAME   - Image name (default: progress)
#   IMAGE_TAG    - Image tag (default: latest). Always builds both $IMAGE_TAG and latest
#   REGISTRY     - Docker registry (default: jukanntenn). Set to empty string to disable
#   PLATFORMS    - Target platforms for push (default: linux/amd64,linux/arm64)
#   PUSH         - Push to registry (default: false). Set to 'true' to enable multi-arch build

set -e

# Configuration variables
IMAGE_NAME="${IMAGE_NAME:-progress}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY="${REGISTRY:-jukanntenn}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
PUSH="${PUSH:-false}"

# Detect host platform for local builds
HOST_ARCH=$(docker version --format '{{.Server.Arch}}' 2>/dev/null || echo "amd64")
case "$HOST_ARCH" in
    x86_64|amd64) HOST_PLATFORM="linux/amd64" ;;
    aarch64|arm64) HOST_PLATFORM="linux/arm64" ;;
    *) HOST_PLATFORM="linux/amd64" ;;  # Fallback
esac

# Build full image name
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME"
else
    FULL_IMAGE_NAME="$IMAGE_NAME"
fi

echo "=========================================="
echo "Building Multi-Architecture Docker Image"
echo "=========================================="
echo "Image Name: $FULL_IMAGE_NAME"
echo "Primary Tag: $IMAGE_TAG"
if [ "$IMAGE_TAG" != "latest" ]; then
    echo "Additional Tag: latest"
fi
if [ "$PUSH" = "true" ]; then
    echo "Platforms: $PLATFORMS (multi-arch push)"
else
    echo "Platforms: $HOST_PLATFORM (local build)"
fi
echo "Registry: $REGISTRY"
echo "Push: $PUSH"
echo "=========================================="

# Ensure buildx is available
echo "Checking Docker buildx..."
docker buildx version >/dev/null 2>&1 || {
    echo "Error: Docker buildx is not available, please ensure you are using a newer version of Docker"
    exit 1
}

# Create and use buildx builder
BUILDER_NAME="multiarch-builder"
if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    echo "Creating buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
else
    echo "Using existing buildx builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi

# Bootstrap builder
docker buildx inspect --bootstrap

# Change to project root directory (parent of docker directory)
cd "$(dirname "$0")/.."

# Build command arguments (without platform, will be added later)
BUILD_ARGS=()

# Add tags
BUILD_ARGS+=(--tag "$FULL_IMAGE_NAME:$IMAGE_TAG")
if [ "$IMAGE_TAG" != "latest" ]; then
    BUILD_ARGS+=(--tag "$FULL_IMAGE_NAME:latest")
fi

# Add platform and push/load flags
if [ "$PUSH" = "true" ]; then
    BUILD_ARGS+=(--platform "$PLATFORMS")
    BUILD_ARGS+=(--push)
    echo "Build mode: Build and Push (multi-arch: $PLATFORMS)"
else
    BUILD_ARGS+=(--platform "$HOST_PLATFORM")
    BUILD_ARGS+=(--load)
    echo "Build mode: Build and Load (local only, platform: $HOST_PLATFORM)"
fi

# Build image
echo "Starting image build..."
echo "Command: docker buildx build ${BUILD_ARGS[*]} -f docker/Dockerfile ."

docker buildx build "${BUILD_ARGS[@]}" -f docker/Dockerfile .

echo "=========================================="
echo "Build completed!"
echo "Image: $FULL_IMAGE_NAME:$IMAGE_TAG"
if [ "$IMAGE_TAG" != "latest" ]; then
    echo "Image: $FULL_IMAGE_NAME:latest"
fi
echo "Platforms: $PLATFORMS"
echo "=========================================="
