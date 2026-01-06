#!/bin/bash
# 多架构 Docker 镜像构建脚本
# 支持: linux/amd64, linux/arm64

set -e

# 配置变量
IMAGE_NAME="${IMAGE_NAME:-progress}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
REGISTRY="${REGISTRY:-}"
PLATFORMS="linux/amd64,linux/arm64"

# 如果设置了 REGISTRY，添加前缀
if [ -n "$REGISTRY" ]; then
    FULL_IMAGE_NAME="$REGISTRY/$IMAGE_NAME"
else
    FULL_IMAGE_NAME="$IMAGE_NAME"
fi

echo "=========================================="
echo "构建多架构 Docker 镜像"
echo "=========================================="
echo "镜像名称: $FULL_IMAGE_NAME"
echo "标签: $IMAGE_TAG"
echo "架构: $PLATFORMS"
echo "=========================================="

# 确保 buildx 可用
echo "检查 Docker buildx..."
docker buildx version >/dev/null 2>&1 || {
    echo "错误: Docker buildx 不可用，请确保使用较新版本的 Docker"
    exit 1
}

# 创建并使用 buildx builder
BUILDER_NAME="multiarch-builder"
if ! docker buildx inspect "$BUILDER_NAME" >/dev/null 2>&1; then
    echo "创建 buildx builder: $BUILDER_NAME"
    docker buildx create --name "$BUILDER_NAME" --driver docker-container --use
else
    echo "使用已存在的 buildx builder: $BUILDER_NAME"
    docker buildx use "$BUILDER_NAME"
fi

# 启动 builder
docker buildx inspect --bootstrap

# 构建并推送镜像
echo "开始构建镜像..."
echo "命令: docker buildx build --platform $PLATFORMS -t $FULL_IMAGE_NAME:$IMAGE_TAG --push ."

docker buildx build \
    --platform "$PLATFORMS" \
    --tag "$FULL_IMAGE_NAME:$IMAGE_TAG" \
    --push \
    .

echo "=========================================="
echo "构建完成！"
echo "镜像: $FULL_IMAGE_NAME:$IMAGE_TAG"
echo "架构: $PLATFORMS"
echo "=========================================="
echo ""
echo "使用方法:"
echo "  docker pull $FULL_IMAGE_NAME:$IMAGE_TAG"
echo "  docker run -v \$(pwd)/config.toml:/app/config.toml -v \$(pwd)/data:/app/data $FULL_IMAGE_NAME:$IMAGE_TAG"
echo ""
echo "或者指定架构拉取:"
echo "  docker pull --platform linux/amd64 $FULL_IMAGE_NAME:$IMAGE_TAG"
echo "  docker pull --platform linux/arm64 $FULL_IMAGE_NAME:$IMAGE_TAG"
