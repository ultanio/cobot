#!/bin/bash
set -euo pipefail

REPO_DIR="/home/alpha/workspace/cobot"
ALPHA_USER="alpha"

echo "=== Deploying Alpha (cobot) ==="
echo "Source: ${1:-manual}"
echo "Running as: $(whoami)"

# If running as root (from CI), fix ownership and switch to alpha
if [ "$(whoami)" = "root" ]; then
    chown -R "$ALPHA_USER:$ALPHA_USER" "$REPO_DIR"
    exec sudo -u "$ALPHA_USER" bash "$0" "$@"
fi

cd "$REPO_DIR"

# Pull latest from forgejo
git fetch forgejo main
git reset --hard forgejo/main

# Install dependencies
if [ -d ".venv" ]; then
    source .venv/bin/activate
    pip install -e . --quiet 2>&1 || echo "⚠️ pip install had issues"
fi

# Restart service
if systemctl --user is-active cobot.service &>/dev/null; then
    systemctl --user restart cobot.service
    echo "✅ Service restarted"
else
    echo "⚠️ cobot.service not active, attempting manual restart"
    pkill -f "cobot run" || true
    sleep 1
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi
    nohup cobot run &>/dev/null &
    echo "✅ Started manually (PID: $!)"
fi

echo "=== Deploy complete ==="
# Deploy test 2026-02-27T10:08:00Z
# Runner restart Fri Feb 27 15:41:58 UTC 2026
