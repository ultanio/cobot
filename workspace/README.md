# Workspace Context Files

This directory contains workspace context files that are deployed to `~/.cobot/workspace/` on the target machine during `deploy.sh`.

## Files

- **SOUL.md** — Agent identity and personality
- **TOOLS.md** — Available tools and environment notes
- **HEARTBEAT.md** — Heartbeat polling instructions (if used)

## How It Works

`deploy.sh` copies all `*.md` files from this directory to `~/.cobot/workspace/`, overwriting existing files. This ensures workspace context is versioned, reviewable, and auto-deployed.

## What NOT to Put Here

- `memory/` files — those are runtime state, not config
- Secrets or credentials
- Large data files
