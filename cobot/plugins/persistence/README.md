# Persistence Plugin

Saves conversation history per peer.


## Table of Contents

- [Overview](#overview)
- [Priority](#priority)
- [Capabilities](#capabilities)
- [Dependencies](#dependencies)
- [Extension Points](#extension-points)
- [Storage Format](#storage-format)
- [Usage](#usage)
- [Integration with Agent](#integration-with-agent)
- [Hooks](#hooks)
- [Configuration](#configuration)

## Overview

The persistence plugin stores conversation history so the agent remembers previous interactions. History is saved per-peer (each person the agent talks to has their own history).

## Priority

**15** — After security, before compaction.

## Capabilities

- `persistence` — Conversation storage

## Dependencies

- `config` — Gets storage path

## Extension Points

**Defines:** None  
**Implements:** None

## Storage Format

```
~/.cobot/workspace/memory/conversations/
├── abc123.json    # Hash of peer ID
├── def456.json
└── ...
```

Each file contains:
```json
{
  "peer": "npub1...",
  "messages": [
    {"role": "user", "content": "Hello", "timestamp": 1707830400},
    {"role": "assistant", "content": "Hi!", "timestamp": 1707830401}
  ],
  "summary": "Previous conversation summary...",
  "last_updated": 1707830401
}
```

## Usage

```python
# Get persistence plugin
persistence = registry.get("persistence")

# Set current peer
persistence.set_peer("npub1abc...")

# Get history
history = persistence.get_history()
# Returns list of messages

# Add message
persistence.add_message("user", "Hello!")
persistence.add_message("assistant", "Hi there!")

# Save (auto-saves periodically)
persistence.save()
```

## Integration with Agent

The agent automatically:
1. Loads history for the current peer on message receive
2. Appends new messages to history
3. Saves after each response

## Extension Points

**Implements:**

| Extension Point | Method | Description |
|-----------------|--------|-------------|
| `loop.on_message` | `on_message_received` | Loads history for the current peer |
| `loop.transform_history` | `transform_history` | Injects saved history into context |
| `loop.after_send` | `on_after_send` | Saves the exchange to disk |

```python
async def on_message_received(self, ctx: dict) -> dict:
    # Load history for this peer
    peer = ctx.get("sender")
    self.set_peer(peer)
    return ctx

async def transform_history(self, ctx: dict) -> dict:
    # Inject saved history
    ctx["messages"] = self.get_history() + ctx["messages"]
    return ctx

async def on_after_send(self, ctx: dict) -> dict:
    # Save the exchange
    self.save()
    return ctx
```

## Configuration

**Default: Disabled** — Each session starts fresh.

Use `--continue` to load previous conversation:
```bash
cobot run --continue    # or -C
cobot run --stdin -C
```

```yaml
# cobot.yml
persistence:
  enabled: true    # Or use --continue flag
  max_messages: 100    # Per conversation (future)
```

Storage location: `~/.cobot/workspace/memory/conversations/`
