#!/bin/bash
set -euo pipefail

REPO_DIR="/home/alpha/workspace/cobot"
ALPHA_USER="alpha"

echo "=== Deploying Alpha (cobot) ==="
echo "Source: ${1:-manual}"
echo "Running as: $(whoami)"

# If running as root (from CI), fix ownership and switch to alpha (#149)
if [ "$(whoami)" = "root" ]; then
    chown -R "$ALPHA_USER:$ALPHA_USER" "$REPO_DIR"
    exec sudo -u "$ALPHA_USER" bash "$0" "$@"
fi

cd "$REPO_DIR"

# Stop existing processes first to prevent duplicates (#139)
pkill -f "cobot run" 2>/dev/null || true
sleep 2
rm -f ~/.cobot/cobot.pid

# Pull latest from forgejo
git fetch forgejo main
git reset --hard forgejo/main

# Deploy workspace context files (#141, #151)
if [ -d "$REPO_DIR/workspace" ]; then
    mkdir -p ~/.cobot/workspace
    for f in "$REPO_DIR"/workspace/*.md; do
        [ -f "$f" ] || continue
        basename=$(basename "$f")
        [ "$basename" = "README.md" ] && continue
        cp "$f" ~/.cobot/workspace/"$basename"
    done
    echo "✅ Workspace context deployed"
fi

# Install dependencies
if [ -d ".venv" ]; then
    source .venv/bin/activate
    pip install -e . --quiet 2>&1 || echo "⚠️ pip install had issues"
fi

# Load environment
if [ -f ~/secrets/cobot.env ]; then
    set -a
    source ~/secrets/cobot.env
    set +a
fi

# Start cobot (single instance)
if systemctl --user is-active cobot.service &>/dev/null; then
    systemctl --user restart cobot.service
    echo "✅ Service restarted"
else
    if [ -d ".venv" ]; then
        source .venv/bin/activate
    fi
    nohup cobot run &>/dev/null &
    echo "✅ Started (PID: $!)"
fi

echo "=== Deploy complete ==="
