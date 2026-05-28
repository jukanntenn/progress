#!/bin/sh
tz="UTC"
if [ -f "$CONFIG_FILE" ]; then
    tz=$(grep '^[[:space:]]*timezone[[:space:]]*=' "$CONFIG_FILE" | cut -d'=' -f2 | tr -d '"\047' | cut -d'#' -f1 | xargs)
    tz=${tz:-UTC}
fi
if [ ! -f "/usr/share/zoneinfo/$tz" ]; then
    echo "[cont-init.d] Warning: Invalid timezone '$tz', using UTC"
    tz="UTC"
fi
ln -snf "/usr/share/zoneinfo/$tz" /etc/localtime
echo "$tz" > /etc/timezone
echo "[cont-init.d] Timezone set to: $tz"
