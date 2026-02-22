# Subagent Plugin

Spawn isolated sessions for delegated work.

## Overview

The subagent plugin enables spawning isolated LLM sessions for:
- Long-running tasks
- Parallel work
- Specialist/delegated tasks

Subagents run **without** conversation history, memory, or main session context. They receive only the explicit task and context you provide.

## Configuration

```yaml
subagent:
  max_concurrent: 3           # Max parallel subagents
  default_timeout_seconds: 300  # 5 minutes default
  max_timeout_seconds: 1800   # 30 minutes max
```

## Usage

### Via Tool (Agent Use)

The main agent can spawn subagents using the `spawn_subagent` tool:

```json
{
  "name": "spawn_subagent",
  "arguments": {
    "task": "Research the history of the Bitcoin whitepaper and summarize",
    "context": "{\"focus\": \"technical innovations\"}",
    "timeout_minutes": 10
  }
}
```

### Via API (Plugin Use)

Other plugins can spawn subagents programmatically:

```python
subagent = registry.get("subagent")
result = await subagent.spawn(
    task="Analyze this code for security issues",
    context={"code": "...", "language": "python"},
    timeout_seconds=300,
)

if result.success:
    print(result.output)
else:
    print(f"Failed: {result.error}")
```

## SubagentResult

```python
@dataclass
class SubagentResult:
    success: bool          # Whether execution succeeded
    output: str            # LLM response content
    task: str              # Original task
    elapsed_seconds: float # Execution time
    error: Optional[str]   # Error message if failed
```

## Extension Points

### subagent.before_spawn

Called before spawning a subagent. Modify task/context:

```python
meta = PluginMeta(
    implements={"subagent.before_spawn": "enrich_task"},
)

async def enrich_task(self, ctx: dict) -> dict:
    # Add default context
    ctx["context"] = ctx.get("context") or {}
    ctx["context"]["timestamp"] = time.time()
    return ctx
```

### subagent.after_spawn

Called after subagent completes. Process results:

```python
meta = PluginMeta(
    implements={"subagent.after_spawn": "log_result"},
)

async def log_result(self, ctx: dict) -> None:
    result = ctx["result"]
    print(f"Subagent completed: {result.task} in {result.elapsed_seconds}s")
```

## Key Properties

- **Isolated**: No conversation history, no memory access
- **Concurrent**: Multiple subagents can run in parallel
- **Timeout**: Prevents runaway execution
- **Tool-accessible**: Main agent can delegate work

## Use Cases

1. **Research tasks**: "Find information about X and summarize"
2. **Code analysis**: "Review this code for issues"
3. **Parallel work**: Spawn multiple subagents for independent subtasks
4. **Specialist work**: Different system prompts for different tasks

## Limitations

- Subagents cannot spawn other subagents (no recursion)
- No tool access by default (isolated execution)
- No persistence of subagent conversations
- Same LLM provider as main agent
