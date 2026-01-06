#!/bin/bash
set -e

# 配置文件路径（可通过环境变量覆盖）
CONFIG_FILE="${CONFIG_FILE:-/app/config.toml}"

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# 检查配置文件是否存在
if [ ! -f "$CONFIG_FILE" ]; then
    log "错误：配置文件不存在: $CONFIG_FILE"
    exit 1
fi

# 检查是否启用调度
SCHEDULE_ENABLED=$(grep -A 3 '^\[schedule\]' "$CONFIG_FILE" | grep '^enabled' | cut -d'=' -f2 | tr -d ' "')
SCHEDULE_ENABLED=${SCHEDULE_ENABLED:-false}

if [ "$SCHEDULE_ENABLED" = "true" ]; then
    # 获取 crontab 配置（移除引号和注释，但保留字段间的空格）
    CRONTAB=$(grep -A 10 '^\[schedule\]' "$CONFIG_FILE" | grep '^crontab' | cut -d'=' -f2 | sed 's/"//g' | sed "s/'//g" | cut -d'#' -f1 | xargs)

    if [ -z "$CRONTAB" ]; then
        log "警告：调度已启用但未配置 crontab，使用默认值 '0 */6 * * *'"
        CRONTAB="0 */6 * * *"
    fi

    log "调度模式已启用"
    log "Crontab: $CRONTAB"

    # 创建 crontab 文件，设置 PATH 环境变量和工作目录
    cat > /tmp/crontab << EOF
PATH=/usr/local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
$CRONTAB cd /app && progress --config "$CONFIG_FILE" >> /proc/1/fd/1 2>&1
EOF

    log "注册定时任务..."
    crontab -u root /tmp/crontab

    log "启动 cron 守护进程..."
    # 启动 cron 并在前台运行
    cron -f &
    CRON_PID=$!

    log "调度器已启动，PID: $CRON_PID"
    log "首次运行以验证配置..."

    # 首次运行一次以验证配置
    progress --config "$CONFIG_FILE"

    log "调度器正在运行，等待定时任务执行..."

    # 等待 cron 进程
    wait $CRON_PID
else
    log "调度模式未启用，单次运行..."
    # 直接运行程序
    exec progress --config "$CONFIG_FILE" "$@"
fi
