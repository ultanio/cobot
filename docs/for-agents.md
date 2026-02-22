# Cobot for Agents

This guide is written for AI agents who need to work with Cobot.

## Quick Reference

### File Locations

| File | Purpose |
|------|---------|
| `cobot.yml` | Main configuration |
| `SOUL.md` | System prompt / personality |
| `memory/` | Conversation history |
| `plugins/` | Local plugins |
| `/opt/cobot/plugins/` | System-wide plugins |

### CLI Commands

```bash
cobot run              # Start agent
cobot run --stdin      # Interactive mode
cobot status           # Check if running
cobot restart          # Restart (sends SIGUSR1)
cobot wallet balance   # Check sats
cobot config show      # Show config
```

### Environment Variables

```bash
PPQ_API_KEY        # PPQ.ai API key
NOSTR_PRIVKEY      # Nostr private key (hex)
NOSTR_NSEC         # Nostr private key (bech32)
```

## Plugin Development (Agent-Friendly)

### Minimal Plugin Template

```python
# plugins/myplugin/plugin.py
from cobot.plugins.base import Plugin, PluginMeta

class MyPlugin(Plugin):
    meta = PluginMeta(
        id="myplugin",
        version="1.0.0",
        capabilities=[],      # What you provide: "llm", "communication", etc.
        dependencies=[],      # Plugins you need loaded first
        priority=50,          # Lower = loads earlier
    )
    
    def configure(self, config: dict) -> None:
        # config is the FULL cobot.yml dict
        # Extract your section:
        self._config = config.get("myplugin", {})
    
    def start(self) -> None:
        # Initialize resources
        pass
    
    def stop(self) -> None:
        # Clean up
        pass

def create_plugin():
    return MyPlugin()
```

### With Extension Points

```python
# Define extension points others can implement
meta = PluginMeta(
    id="myplugin",
    version="1.0.0",
    extension_points=["myplugin.before_action", "myplugin.after_action"],
)

# Call them in your code
def do_action(self, data):
    ctx = self.call_extension("myplugin.before_action", {"data": data})
    if ctx.get("abort"):
        return None
    
    result = self._process(ctx["data"])
    
    ctx = self.call_extension("myplugin.after_action", {"result": result})
    return ctx.get("result", result)
```

### Implementing Extension Points

```python
# Implement another plugin's extension point
meta = PluginMeta(
    id="myplugin",
    version="1.0.0",
    implements={
        "otherplugin.before_action": "my_handler",
    },
)

def my_handler(self, ctx: dict) -> dict:
    # Modify context
    ctx["data"] = transform(ctx["data"])
    # Or abort processing
    # ctx["abort"] = True
    return ctx
```

## Extension Points (Loop Plugin)

The loop plugin defines extension points for the message lifecycle. Implement them via `meta.implements`:

```python
meta = PluginMeta(
    id="myplugin",
    version="1.0.0",
    implements={
        "loop.on_message": "handle_message",
        "loop.before_llm": "modify_prompt",
    },
)

async def handle_message(self, ctx: dict) -> dict:
    # ctx["message"], ctx["sender"]
    return ctx

async def modify_prompt(self, ctx: dict) -> dict:
    # ctx["messages"], ctx["tools"]
    return ctx
```

### Available Extension Points

| Extension Point | Context | Description |
|-----------------|---------|-------------|
| `loop.on_message` | message, sender | Message received |
| `loop.transform_system_prompt` | prompt | Modify system prompt |
| `loop.transform_history` | messages | Modify conversation history |
| `loop.before_llm` | messages, tools | Before LLM call |
| `loop.after_llm` | response | After LLM response |
| `loop.before_tool` | tool, args | Before tool execution |
| `loop.after_tool` | tool, result | After tool execution |
| `loop.transform_response` | response | Modify final response |
| `loop.before_send` | text, recipient | Before sending |
| `loop.after_send` | text, recipient | After sending |
| `loop.on_error` | error | Error occurred |

### Aborting Processing

Set `ctx["abort"] = True` to stop the chain:

```python
async def handle_message(self, ctx: dict) -> dict:
    if is_spam(ctx["message"]):
        ctx["abort"] = True
        ctx["abort_message"] = "Message blocked"
    return ctx
```

## Registry API

Access other plugins:

```python
# In your plugin
registry = self._registry

# Get plugin by ID
config_plugin = registry.get("config")

# Get by capability
llm = registry.get_by_capability("llm")
comms = registry.get_by_capability("communication")

# Get all with capability
all_llms = registry.all_with_capability("llm")

# List all plugins
plugins = registry.list_plugins()
```

## FileDrop Protocol

File-based agent-to-agent communication.

### Directory Structure

```
/tmp/filedrop/
├── AgentA/
│   ├── inbox/     # Incoming messages
│   ├── outbox/    # Sent messages (debug)
│   ├── processed/ # Handled messages
│   └── rejected/  # Invalid messages
└── AgentB/
    └── inbox/
```

### Message Format

```json
{
  "id": "1707123456_abc123",
  "from": "AgentA",
  "to": "AgentB",
  "content": "Hello!",
  "timestamp": 1707123456,
  "sent_at": "2026-02-05T12:30:56Z",
  "nostr_sig": "...",      // Optional: Schnorr signature
  "nostr_pubkey": "..."    // Optional: Sender's pubkey
}
```

### Send Message

```python
comms = registry.get_by_capability("communication")
msg_id = comms.send("AgentB", "Hello!")
```

### Receive Messages

```python
comms = registry.get_by_capability("communication")
messages = comms.receive(since_minutes=5)
for msg in messages:
    print(f"From {msg.sender}: {msg.content}")
```

## Hot Reload

The `hotreload` plugin watches directories and auto-restarts on changes.

### Configuration

```yaml
hotreload:
  enabled: true
  watch:
    - /opt/cobot/plugins
    - ./plugins
  interval: 3.0
  patterns:
    - "*.py"
```

### Trigger Manually

```bash
# Send SIGUSR1
kill -USR1 $(cat ~/.cobot/cobot.pid)

# Or use CLI
cobot restart
```

## Testing Plugins

```python
# tests/test_myplugin.py
import pytest
from cobot.plugins.registry import PluginRegistry, reset_registry

@pytest.fixture
def registry():
    reset_registry()
    return PluginRegistry()

def test_myplugin(registry):
    from plugins.myplugin.plugin import MyPlugin
    
    registry.register(MyPlugin)
    registry.configure_all({"myplugin": {"key": "value"}})
    registry.start_all()
    
    plugin = registry.get("myplugin")
    assert plugin is not None
    
    registry.stop_all()
```

## Debugging Tips

1. **Check logs:** Look for `[PluginName]` prefixed messages in stderr
2. **Registry state:** `registry.list_plugins()` shows all loaded plugins
3. **Extension points:** `registry.list_extension_points()` shows hooks
4. **Hot reload:** Touch a file to trigger restart and see load order

## Common Patterns

### Singleton Config Access

```python
from cobot.plugins.config import get_config

config = get_config()
print(config.provider)  # "ppq"
```

### Conditional Plugin Loading

```yaml
# cobot.yml
plugins:
  disabled:
    - nostr  # Skip this plugin
```

### Priority-Based Loading

Lower priority = loads first. Use for dependencies:

```python
meta = PluginMeta(
    id="base-plugin",
    priority=10,  # Loads early
)

meta = PluginMeta(
    id="dependent-plugin",
    priority=50,
    dependencies=["base-plugin"],
)
```

## Scheduled Execution

### Spawning Subagents

Use the `spawn_subagent` tool to delegate work:

```json
{
  "name": "spawn_subagent",
  "arguments": {
    "task": "Research topic X and summarize",
    "context": "{\"focus\": \"technical details\"}",
    "timeout_minutes": 10
  }
}
```

Or via plugin API:

```python
subagent = registry.get("subagent")
result = await subagent.spawn(
    task="Analyze this code",
    context={"code": "..."},
    timeout_seconds=300,
)
if result.success:
    print(result.output)
```

### Cron Jobs

Schedule periodic tasks:

```yaml
cron:
  jobs:
    # Isolated mode - spawns subagent
    - name: daily-report
      schedule: "0 9 * * *"
      mode: isolated
      prompt: "Generate daily summary"
    
    # Main session mode - injects into main session
    - name: inbox-check
      schedule: "*/30 * * * *"
      mode: main_session
      prompt: "Check filedrop inbox"
```

Dynamic job management:

```python
cron = registry.get("cron")

# Add job
cron.add_job({
    "name": "custom-task",
    "schedule": "1h",
    "mode": "isolated",
    "prompt": "Do something",
})

# Remove job
cron.remove_job("custom-task")
```

### Heartbeat

Periodic main session wake-up:

```yaml
heartbeat:
  enabled: true
  interval_minutes: 15
  prompt_file: HEARTBEAT.md
  quiet_hours: "23:00-07:00"
```

Create `HEARTBEAT.md`:

```markdown
## Heartbeat Check

1. Check filedrop inbox
2. Review pending tasks
3. Commit workspace changes

Reply HEARTBEAT_OK if nothing needs attention.
```

## Agent-to-Agent Protocol

For agents communicating with other Cobot instances:

1. **Identity:** Exchange npubs
2. **Communication:** Use FileDrop or Nostr DMs
3. **Authentication:** Sign messages with Schnorr (filedrop-nostr plugin)
4. **Payments:** Lightning invoices via wallet plugin

Example flow:

```
Agent A                          Agent B
   │                                │
   │──── FileDrop (signed) ────────►│
   │                                │
   │◄─── FileDrop (signed) ─────────│
   │                                │
   │──── Lightning invoice ────────►│
   │                                │
   │◄─── Payment (sats) ────────────│
```
