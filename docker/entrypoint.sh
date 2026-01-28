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

# Start web service if enabled
start_web_service() {
    local web_enabled="false"

    # Read web.enabled configuration from file
    if [ -f "$CONFIG_FILE" ]; then
        web_enabled=$(grep -A2 '^\[web\]' "$CONFIG_FILE" | grep '^[[:space:]]*enabled[[:space:]]*=' | cut -d'=' -f2 | tr -d '"\047' | cut -d'#' -f1 | xargs | tr '[:upper:]' '[:lower:]')
        web_enabled=${web_enabled:-false}
    fi

    if [ "$web_enabled" = "true" ]; then
        log "Starting web service..."
        export PYTHONPATH=/app/src

        # Read web host and port from config
        local web_host=$(grep -A5 '^\[web\]' "$CONFIG_FILE" | grep '^[[:space:]]*host[[:space:]]*=' | cut -d'=' -f2 | tr -d '"\047' | cut -d'#' -f1 | xargs)
        local web_port=$(grep -A5 '^\[web\]' "$CONFIG_FILE" | grep '^[[:space:]]*port[[:space:]]*=' | cut -d'=' -f2 | tr -d '"\047' | cut -d'#' -f1 | xargs)
        web_host=${web_host:-0.0.0.0}
        web_port=${web_port:-5000}

        # Try gunicorn first, fallback to python
        if command -v gunicorn >/dev/null 2>&1; then
            log "Using gunicorn to start web service..."
            gunicorn -w 2 -b "$web_host:$web_port" \
                --access-logfile - \
                --error-logfile - \
                --log-level info \
                --capture-output \
                "progress.web:create_app()" &
        else
            log "Gunicorn not found, using Flask development server..."
            cat > /tmp/run_web.py << 'EOFPYTHON'
import sys
sys.path.insert(0, '/app/src')

from progress.config import Config
from progress.web import create_app

config = Config.load_from_file('/app/config.toml')
app = create_app(config)
app.run(host='0.0.0.0', port=5000, debug=False)
EOFPYTHON
            python /tmp/run_web.py &
        fi

        local web_pid=$!
        sleep 2

        # Check if web service is still running
        if kill -0 $web_pid 2>/dev/null; then
            log "Web service started on http://$web_host:$web_port (PID: $web_pid)"
        else
            log "Error: Web service failed to start. Check logs above for errors."
        fi
    else
        log "Web service is disabled"
    fi
}

# Configure SSH to automatically accept new host keys (solves SSH connection issues in Docker containers)
log "Configuring SSH client..."
mkdir -p ~/.ssh
chmod 700 ~/.ssh
git config --global core.sshCommand 'ssh -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=~/.ssh/known_hosts'
log "SSH configuration completed"

# Setup timezone
setup_timezone

# Start web service if enabled
start_web_service

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
