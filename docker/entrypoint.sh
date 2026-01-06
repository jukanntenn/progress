#!/bin/bash
set -e

# Configuration file path (can be overridden by environment variable)
CONFIG_FILE="${CONFIG_FILE:-/app/config.toml}"

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

# Setup timezone (read from configuration file)
setup_timezone() {
    local tz="UTC"

    # Read timezone configuration from file
    if [ -f "$CONFIG_FILE" ]; then
        tz=$(grep '^[[:space:]]*timezone[[:space:]]*=' "$CONFIG_FILE" | cut -d'=' -f2 | tr -d '"\047' | cut -d'#' -f1 | xargs)
        tz=${tz:-UTC}
    fi

    # Validate timezone
    if [ ! -f "/usr/share/zoneinfo/$tz" ]; then
        log "Warning: Invalid timezone configuration '$tz', using default UTC"
        tz="UTC"
    fi

    # Set system timezone
    ln -snf "/usr/share/zoneinfo/$tz" /etc/localtime
    echo "$tz" > /etc/timezone
    log "Timezone set to: $tz"
}

# Configure SSH to automatically accept new host keys (solves SSH connection issues in Docker containers)
log "Configuring SSH client..."
mkdir -p ~/.ssh
chmod 700 ~/.ssh
git config --global core.sshCommand 'ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=~/.ssh/known_hosts'
log "SSH configuration completed"

# Setup timezone
setup_timezone

# Create supercronic configuration directory
mkdir -p /etc/supercronic

# Check if configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
    log "Error: Configuration file does not exist: $CONFIG_FILE"
    exit 1
fi

# Check if schedule environment variable is set
if [ -n "$PROGRESS_SCHEDULE_CRON" ]; then
    log "Schedule mode enabled"
    log "Crontab: $PROGRESS_SCHEDULE_CRON"

    # Save environment variables for supercronic
    export CONFIG_FILE="$CONFIG_FILE"

    # Create supercronic crontab file using simple format
    cat > /etc/supercronic/crontab << EOF
PATH=/root/.local/bin:/usr/local/bin:/usr/local/sbin:/usr/bin:/usr/sbin:/sbin:/bin
PYTHONUNBUFFERED=1
PYTHONPATH=/app/src
$PROGRESS_SCHEDULE_CRON cd /app && /usr/local/bin/progress --config /app/config.toml 2>&1
EOF

    log "Generated crontab content:"
    cat /etc/supercronic/crontab

    log "Validating crontab format..."
    if supercronic -test /etc/supercronic/crontab; then
        log "Crontab format validation passed"
    else
        log "Error: Invalid crontab format: $PROGRESS_SCHEDULE_CRON"
        exit 1
    fi

    log "First run to verify configuration..."
    /usr/local/bin/progress --config "$CONFIG_FILE"

    log "Starting supercronic scheduler..."
    exec /usr/local/bin/supercronic -passthrough-logs /etc/supercronic/crontab
else
    log "Single run mode..."
    exec /usr/local/bin/progress --config "$CONFIG_FILE" "$@"
fi
