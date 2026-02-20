# Tools Plugin

Provides tool execution for the agent.


## Table of Contents

- [Overview](#overview)
- [Priority](#priority)
- [Capabilities](#capabilities)
- [Dependencies](#dependencies)
- [Extension Points](#extension-points)
- [Available Tools](#available-tools)
- [Configuration](#configuration)
- [Usage](#usage)
- [Tool Definitions Format](#tool-definitions-format)
- [Security](#security)

## Overview

The tools plugin exposes capabilities to the LLM as function calls. It handles file operations, command execution, and integrates with other plugins (wallet).

## Priority

**30** — After config and LLM plugins.

## Capabilities

- `tools` — Provides tool definitions and execution

## Dependencies

- `config` — Gets exec settings

## Extension Points

**Defines:** None  
**Implements:** None

The tools plugin is accessed via the `tools` capability interface. The loop plugin
calls `tools.get_definitions()` and `tools.execute()` directly during the tool call
cycle. Tool execution is gated by `loop.before_tool` / `loop.after_tool` extension
points (defined by the loop plugin) which other plugins can implement for security
filtering or logging.

## Available Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read contents of a file |
| `write_file` | Write content to a file |
| `edit_file` | Replace text in a file |
| `exec` | Execute shell commands |
| `restart_self` | Request agent restart |
| `wallet_balance` | Get wallet balance |
| `wallet_pay` | Pay Lightning invoice |
| `wallet_receive` | Get receive address |

## Configuration

```yaml
# cobot.yml
exec:
  enabled: true              # Enable/disable exec tool
  blocklist:                 # Blocked command patterns
    - "rm -rf"
    - "sudo"
    - ":(){:|:&};:"
  allowlist: []              # If set, only these commands allowed
  timeout: 30                # Command timeout in seconds
```

## Usage

```python
# Get tools plugin
tools = registry.get("tools")

# Get tool definitions (for LLM)
definitions = tools.get_definitions()
# Returns OpenAI-format function definitions

# Execute a tool
result = tools.execute("read_file", {"path": "/tmp/test.txt"})

# Check if restart requested
if tools.restart_requested:
    # Handle restart
```

## Tool Definitions Format

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read contents of a file",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"}
            },
            "required": ["path"]
        }
    }
}
```

## Security

- Protected paths: Cannot write to `cobot/plugins/*.py`
- Exec blocklist: Dangerous commands blocked by default
- Timeout: Commands killed after timeout
- Disabled by default in untrusted environments
