# Cron Plugin

Scheduled job execution with two modes: isolated and main session.

## Overview

The cron plugin enables scheduling periodic tasks:
- **Isolated mode**: Jobs run via subagent (no context)
- **Main session mode**: Jobs inject into the main agent session (full context)

## Configuration

```yaml
cron:
  jobs:
    # Isolated job - runs via subagent
    - name: daily-report
      schedule: "0 9 * * *"
      mode: isolated
      prompt: "Generate a summary of yesterday's activity."
      output:
        type: telegram
        target: "-1001234567890"
    
    # Main session job - injects into main session (heartbeat pattern)
    - name: heartbeat
      schedule: "*/15 * * * *"
      mode: main_session
      prompt_file: HEARTBEAT.md
      quiet_hours: "23:00-07:00"
```

## Job Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | required | Unique job identifier |
| `schedule` | string | required | Cron expression or interval |
| `mode` | string | `isolated` | `isolated` or `main_session` |
| `prompt` | string | - | Inline prompt text |
| `prompt_file` | string | - | Path to prompt file |
| `system_prompt` | string | - | Override system prompt (isolated only) |
| `quiet_hours` | string | - | Skip during these hours (e.g., `23:00-07:00`) |
| `output` | object | - | Output routing config |
| `enabled` | bool | `true` | Enable/disable job |

## Schedule Format

### Simple Intervals

```yaml
schedule: "15m"   # Every 15 minutes
schedule: "1h"    # Every hour
```

### Cron Expressions

```yaml
schedule: "*/15 * * * *"  # Every 15 minutes
schedule: "0 9 * * *"     # Daily at 9:00 AM
schedule: "0 3 * * 0"     # Sundays at 3:00 AM
```

## Execution Modes

### Isolated Mode

Jobs run in a fresh session via the subagent plugin:
- No conversation history
- No memory context
- Independent execution

```yaml
- name: cleanup
  mode: isolated
  prompt: "Run maintenance tasks and report results."
```

### Main Session Mode

Jobs inject a message into the main agent session:
- Full conversation history
- Memory access
- Same context as regular messages

```yaml
- name: heartbeat
  mode: main_session
  prompt_file: HEARTBEAT.md
```

## Output Routing

### Log (default)

```yaml
output:
  type: log
```

### File

```yaml
output:
  type: file
  target: "~/reports/daily.txt"
```

### Telegram

```yaml
output:
  type: telegram
  target: "-1001234567890"  # Chat ID
```

### FileDrop

```yaml
output:
  type: filedrop
  target: "Zeus"  # Recipient agent
```

## Dynamic Job Management

Plugins can add/remove jobs at runtime:

```python
cron = registry.get("cron")

# Add a job
job_name = cron.add_job({
    "name": "dynamic-task",
    "schedule": "30m",
    "mode": "isolated",
    "prompt": "Do something useful",
})

# Remove a job
cron.remove_job("dynamic-task")
```

## Extension Points

### cron.before_job

Modify job parameters before execution:

```python
async def modify_prompt(self, ctx: dict) -> dict:
    ctx["prompt"] = f"Current time: {datetime.now()}\n\n" + ctx["prompt"]
    return ctx
```

### cron.after_job

Process results after job completion:

```python
async def log_completion(self, ctx: dict) -> None:
    result = ctx["result"]
    print(f"Job {ctx['job'].name} completed in {result.elapsed_seconds}s")
```

## Quiet Hours

Skip job execution during specified hours:

```yaml
quiet_hours: "23:00-07:00"  # Overnight
quiet_hours: "12:00-13:00"  # Lunch break
```

## Agent Tools

The cron plugin provides tools for agents to manage jobs dynamically:

### cron_add_job

Add a new scheduled job:

```json
{
  "name": "cron_add_job",
  "arguments": {
    "name": "daily-check",
    "schedule": "0 9 * * *",
    "prompt": "Check for updates and report",
    "mode": "isolated"
  }
}
```

### cron_remove_job

Remove a job by name:

```json
{
  "name": "cron_remove_job",
  "arguments": {
    "name": "daily-check"
  }
}
```

Note: System jobs (prefixed with `__`) cannot be removed via tool.

### cron_list_jobs

List all configured jobs:

```json
{
  "name": "cron_list_jobs",
  "arguments": {}
}
```

## Integration with Heartbeat

The heartbeat plugin uses cron internally:

```python
# Heartbeat plugin adds a main_session job
cron.add_job({
    "name": "__heartbeat__",
    "schedule": "*/15 * * * *",
    "mode": "main_session",
    "prompt_file": "HEARTBEAT.md",
})
```
