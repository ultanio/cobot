# Heartbeat Plugin

Periodic main session wake-up for proactive agent work.

## Overview

The heartbeat plugin provides a simple way to periodically wake up your agent with full session context. It's a convenience wrapper around the cron plugin.

Unlike cron jobs in isolated mode, heartbeat runs in the **main session** with:
- Full conversation history
- Memory access
- SOUL.md context

## Configuration

```yaml
heartbeat:
  enabled: true
  interval_minutes: 15
  prompt_file: HEARTBEAT.md
  quiet_hours: "23:00-07:00"
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Enable heartbeat |
| `interval_minutes` | `15` | Minutes between heartbeats |
| `prompt_file` | `HEARTBEAT.md` | Path to heartbeat instructions |
| `quiet_hours` | - | Skip during these hours |

## HEARTBEAT.md

Create a `HEARTBEAT.md` file with instructions for the agent:

```markdown
## Heartbeat Check

This is a periodic heartbeat. Do useful maintenance work:

1. Check your inbox for new messages
2. Review any pending tasks
3. Commit workspace changes if needed
4. Update memory with important learnings

If nothing needs attention, respond with: HEARTBEAT_OK
```

If the file doesn't exist, a default is created automatically.

## How It Works

1. Heartbeat plugin registers a cron job with `mode: main_session`
2. Cron plugin injects the heartbeat as an `IncomingMessage`
3. Main agent processes it like any other message
4. Agent has full context (history, memory, SOUL.md)

## Quiet Hours

Skip heartbeats during specified hours:

```yaml
quiet_hours: "23:00-07:00"  # Skip overnight
```

## Comparison with Cron

| Feature | Heartbeat | Cron (isolated) | Cron (main_session) |
|---------|-----------|-----------------|---------------------|
| Config | Simple | Full | Full |
| Context | Main session | None | Main session |
| Use case | Proactive work | Scheduled tasks | Custom triggers |

Heartbeat is just syntactic sugar for:

```yaml
cron:
  jobs:
    - name: __heartbeat__
      schedule: "*/15 * * * *"
      mode: main_session
      prompt_file: HEARTBEAT.md
```

## Best Practices

1. **Keep heartbeat prompt focused** — don't overload with tasks
2. **Use quiet hours** — avoid late-night wake-ups
3. **Respect HEARTBEAT_OK** — downstream systems can detect "nothing to do"
4. **Log important work** — heartbeat responses aren't persisted by default
