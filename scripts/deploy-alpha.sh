#!/usr/bin/env bash
###############################################################################
# ⚠️  WARNING: THIS FILE IS VERSION-CONTROLLED                               #
#                                                                             #
# The canonical version lives in the git repo:                                #
#   scripts/deploy-alpha.sh                                                   #
#                                                                             #
# The CI workflow copies this file to Alpha before every deploy.              #
# If you edit the copy on olymp (/home/alpha/workspace/cobot/scripts/),       #
# your changes WILL BE OVERWRITTEN on the next deploy!                        #
#                                                                             #
# → Always commit changes to git first, then let CI sync it.                  #
###############################################################################
#
# Deploy latest cobot main to Alpha's instance
# Usage: deploy-alpha.sh [forgejo|origin] [--no-restart]
set -euo pipefail

REPO_DIR="${COBOT_REPO_DIR:-/home/alpha/workspace/cobot}"
SERVICE="${COBOT_SERVICE:-cobot}"
REMOTE="forgejo"
RESTART=true
SKIP_PULL=false
LOG_FILE="/var/log/cobot-deploy.log"
FILEDROP="/olymp/filedrop"

for arg in "$@"; do
    case "$arg" in
        --no-restart) RESTART=false ;;
        --pulled)     SKIP_PULL=true ;;
        forgejo|origin) REMOTE="$arg" ;;
    esac
done

# --- Logging ---

log() {
    local msg="[$(date -u '+%Y-%m-%d %H:%M:%S UTC')] $*"
    echo "$msg"
    echo "$msg" >> "$LOG_FILE" 2>/dev/null || true
}

log_result() {
    local status="$1" version="$2" details="$3"
    log "$status | version=$version | $details"

    # Broadcast via filedrop
    if command -v filedrop &>/dev/null; then
        filedrop broadcast "Deploy $status: Alpha" \
            "Alpha deployed to $version — $details" 2>/dev/null || true
    elif [[ -d "$FILEDROP" ]]; then
        # Manual broadcast to known agents
        local timestamp msg_id
        timestamp=$(date +%s)
        for agent_dir in "$FILEDROP"/*/inbox; do
            agent=$(basename "$(dirname "$agent_dir")")
            msg_id="${timestamp}_deploy_${RANDOM}"
            cat > "$agent_dir/${msg_id}.json" 2>/dev/null <<ENDJSON || true
{
  "id": "${msg_id}",
  "from": "deploy",
  "to": "${agent}",
  "subject": "Deploy ${status}: Alpha → ${version}",
  "content": "${details}",
  "timestamp": ${timestamp}
}
ENDJSON
        done
    fi
}

cd "$REPO_DIR"

log "Starting deploy from $REMOTE/main..."

# Capture current version before pull
OLD_VERSION=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

if $SKIP_PULL; then
    log "Skipping pull (--pulled)"
else
    # Stash local changes
    if ! git diff --quiet 2>/dev/null; then
        log "Stashing local changes..."
        git stash --include-untracked -q
        STASHED=true
    else
        STASHED=false
    fi

    # Pull latest
    log "Pulling $REMOTE main..."
    PULL_OUTPUT=$(git pull "$REMOTE" main --ff-only 2>&1) || {
        log "ERROR: git pull failed: $PULL_OUTPUT"
        log_result "FAILED" "$OLD_VERSION" "git pull failed"
        exit 1
    }
    echo "$PULL_OUTPUT" | sed 's/^/  /'
fi

NEW_VERSION=$(git rev-parse --short HEAD)
COMMIT_MSG=$(git log -1 --format="%s" 2>/dev/null || echo "")

# Pop stash (only if we stashed)
if ! $SKIP_PULL && $STASHED; then
    log "Restoring local changes..."
    git stash pop -q 2>/dev/null || {
        log "WARNING: stash conflict — check manually"
    }
fi

# Check if anything changed
if [[ "$OLD_VERSION" == "$NEW_VERSION" ]]; then
    log "Already up to date ($NEW_VERSION)"
    log_result "OK" "$NEW_VERSION" "Already up to date, no restart needed"
    exit 0
fi

log "Updated: $OLD_VERSION → $NEW_VERSION ($COMMIT_MSG)"

# Copy integration tests to shared location
if [ -d "$REPO_DIR/tests/integration" ]; then
    log "Copying integration tests to /olymp/shared/tests/"
    mkdir -p /olymp/shared/tests
    cp -a "$REPO_DIR/tests/integration/"* /olymp/shared/tests/
    chmod +x /olymp/shared/tests/*.sh 2>/dev/null || true
fi

# Restart service
if $RESTART; then
    log "Restarting $SERVICE..."
    systemctl --user restart "$SERVICE"
    sleep 3

    if systemctl --user is-active --quiet "$SERVICE"; then
        log "✅ $SERVICE is running"
        log_result "SUCCESS" "$NEW_VERSION" "$OLD_VERSION → $NEW_VERSION: $COMMIT_MSG"
    else
        log "❌ $SERVICE failed to start!"
        journalctl --user -u "$SERVICE" -n 20 --no-pager 2>&1 | sed 's/^/  /'
        log_result "FAILED" "$NEW_VERSION" "Service failed to start after update to $NEW_VERSION"
        exit 1
    fi
else
    log "Skipping restart (--no-restart)"
    log_result "SUCCESS" "$NEW_VERSION" "$OLD_VERSION → $NEW_VERSION (no restart): $COMMIT_MSG"
fi

log "🎉 Deploy complete"
