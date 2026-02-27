#!/usr/bin/env bash
set -euo pipefail

# Deploy script for Cobot (called by CI or manually)
# Handles root→alpha user switch when invoked via SSH as root.

COBOT_USER="${COBOT_USER:-alpha}"
COBOT_DIR="${COBOT_DIR:-/home/${COBOT_USER}/workspace/cobot}"
COBOT_WORKSPACE="${COBOT_WORKSPACE:-/home/${COBOT_USER}/.cobot/workspace}"
SECRETS_ENV="${SECRETS_ENV:-/home/${COBOT_USER}/secrets/cobot.env}"

# If running as root, re-exec as the cobot user
if [ "$(whoami)" = "root" ]; then
    exec sudo -u "$COBOT_USER" "$0" "$@"
fi

cd "$COBOT_DIR"

# --- Stop existing process(es) first (#139) ---
# Kill ALL cobot processes to prevent duplicates
if [ -f ~/.cobot/cobot.pid ]; then
    pid=$(cat ~/.cobot/cobot.pid)
    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping cobot (PID: $pid)..."
        kill "$pid" 2>/dev/null || true
        # Wait for graceful shutdown
        for i in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 1
        done
        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid" 2>/dev/null || true
        fi
    fi
    rm -f ~/.cobot/cobot.pid
fi

# Also kill any stray cobot processes (e.g. root-owned duplicates)
pkill -f "cobot run" 2>/dev/null || true
sleep 1

# Fetch and reset to latest main
git fetch forgejo main
git reset --hard forgejo/main

# --- Deploy workspace context files (#141) ---
if [ -d "$COBOT_DIR/workspace" ]; then
    mkdir -p "$COBOT_WORKSPACE"
    for f in "$COBOT_DIR"/workspace/*.md; do
        [ -f "$f" ] || continue
        basename=$(basename "$f")
        # Skip README.md — it's repo documentation, not agent context
        [ "$basename" = "README.md" ] && continue
        cp "$f" "$COBOT_WORKSPACE/$basename"
    done
    echo "✓ Workspace context files deployed to $COBOT_WORKSPACE"
fi

# Load environment if secrets file exists
if [ -f "$SECRETS_ENV" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$SECRETS_ENV"
    set +a
fi

# Install dependencies
pip install -e ".[all]" --quiet 2>&1 | tail -3

# Start cobot (single instance)
if systemctl --user is-active cobot.service &>/dev/null; then
    systemctl --user restart cobot.service
    echo "✓ Cobot service restarted"
else
    nohup cobot run &>/dev/null &
    echo "✓ Cobot started (PID: $!)"
fi
