#!/usr/bin/env bash
set -euo pipefail

# Deploy script for Cobot (called by CI or manually)
# Handles root→alpha user switch when invoked via SSH as root.

COBOT_USER="${COBOT_USER:-alpha}"
COBOT_DIR="${COBOT_DIR:-/home/${COBOT_USER}/workspace/cobot}"
SECRETS_ENV="${SECRETS_ENV:-/home/${COBOT_USER}/secrets/cobot.env}"

# If running as root, re-exec as the cobot user
if [ "$(whoami)" = "root" ]; then
    exec sudo -u "$COBOT_USER" "$0" "$@"
fi

cd "$COBOT_DIR"

# Fetch and reset to latest main
git fetch forgejo main
git reset --hard forgejo/main

# Load environment if secrets file exists
if [ -f "$SECRETS_ENV" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_ENV"
    set +a
fi

# Install dependencies
pip install -e ".[all]" --quiet 2>&1 | tail -3

# Restart cobot
if systemctl --user is-active cobot.service &>/dev/null; then
    systemctl --user restart cobot.service
    echo "✓ Cobot service restarted"
elif [ -f ~/.cobot/cobot.pid ]; then
    pid=$(cat ~/.cobot/cobot.pid)
    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid"
        sleep 2
    fi
    cd "$COBOT_DIR"
    nohup cobot run &>/dev/null &
    echo "✓ Cobot restarted (PID: $!)"
else
    cd "$COBOT_DIR"
    nohup cobot run &>/dev/null &
    echo "✓ Cobot started (PID: $!)"
fi
