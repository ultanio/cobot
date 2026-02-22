# Loop Plugin

The main agent message loop, extracted from `agent.py` into a plugin.


## Table of Contents

- [Overview](#overview)
- [Priority](#priority)
- [Capabilities](#capabilities)
- [Dependencies](#dependencies)
- [Extension Points](#extension-points)
- [Pipeline](#pipeline)
- [Abort Semantics](#abort-semantics)
- [Configuration](#configuration)
- [Multiple Loops](#multiple-loops)
- [Error Handling](#error-handling)


## Overview

The loop plugin implements the core poll → process → respond cycle. By extracting
this from `agent.py`, the agent becomes a minimal runner (~10 lines) that
`asyncio.gather`s all plugins with the `loop` capability.

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  Agent   │────▶│   Loop   │────▶│  Comm    │
│ (runner) │     │ (plugin) │◀────│  Plugin  │
└──────────┘     └──────────┘     └──────────┘
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
     [LLM Plugin] [Tools Plugin] [Extension chain]
```

## Priority

**50** — After all service plugins (config, communication, session, LLM, tools).

## Capabilities

- `loop` — Main message processing loop

## Dependencies

- `config` — Soul path, polling interval
- `communication` — Message polling and sending

## Extension Points

The loop plugin **defines** these extension points. Other plugins **implement** them
to participate in the message processing pipeline.

| Extension Point | Type | Description |
|-----------------|------|-------------|
| `session.poll_messages` | collect | Inject messages into the loop (used by cron). |
| `loop.on_message` | chain | Called when a message arrives. Can filter/transform. |
| `loop.transform_system_prompt` | chain | Modify the system prompt before LLM call. |
| `loop.transform_history` | chain | Modify conversation history before LLM call. |
| `loop.before_llm` | chain | Called before LLM inference. Can abort. |
| `loop.after_llm` | chain | Called after LLM inference with response metadata. |
| `loop.before_tool` | chain | Called before tool execution. Can abort. |
| `loop.after_tool` | chain | Called after tool execution with result. |
| `loop.transform_response` | chain | Modify the response text before sending. |
| `loop.before_send` | chain | Called before sending response. Can abort. |
| `loop.after_send` | chain | Called after successful send. |
| `loop.on_error` | chain | Called on any error in the pipeline. |

## Pipeline

```
comm.poll() ←──────────────────┐
    │                          │
    ▼                          │
session.poll_messages ─────────┤ (merge)
    │                          │
    ├──────────────────────────┘
    ▼
loop.on_message ──── abort? → stop
    │
    ▼
loop.transform_system_prompt
    │
    ▼
loop.transform_history
    │
    ▼
loop.before_llm ──── abort? → return abort_message
    │
    ▼
LLM.chat()
    │
    ▼
loop.after_llm
    │
    ├── tool_calls? ──┐
    │                  ▼
    │          loop.before_tool ── abort? → use abort_message
    │                  │
    │                  ▼
    │            tools.execute()
    │                  │
    │                  ▼
    │          loop.after_tool
    │                  │
    │                  ▼
    │            LLM.chat() (with tool results) ← loop up to 10 rounds
    │
    ▼
loop.transform_response
    │
    ▼
loop.before_send ──── abort? → stop
    │
    ▼
comm.send()
    │
    ▼
loop.after_send
```

## Abort Semantics

Extension points marked "can abort" support aborting the pipeline:

```python
async def my_security_check(self, ctx: dict) -> dict:
    if is_suspicious(ctx):
        ctx["abort"] = True
        ctx["abort_message"] = "Request blocked by security policy."
    return ctx
```

- `loop.on_message`: Aborts entire message handling (no LLM call, no send)
- `loop.before_llm`: Returns `abort_message` as the response text
- `loop.before_tool`: Uses `abort_message` as tool result (LLM sees it)
- `loop.before_send`: Suppresses sending (message is silently dropped)

## Configuration

```yaml
# cobot.yml — no loop-specific config needed
# Uses config plugin for soul_path and polling_interval
```

## Multiple Loops

The agent runs all `loop`-capability plugins concurrently:

```python
# In agent.py
loops = registry.all_with_capability("loop")
await asyncio.gather(*[loop.run() for loop in loops])
```

This enables concurrent loops like:
- **Main loop** — message processing (this plugin)
- **DVM loop** — NIP-90 job processing
- **Heartbeat loop** — periodic health checks
- **Cron loop** — scheduled task execution

Each loop plugin is independent and defines its own extension points.

## Error Handling

- Poll errors are caught and forwarded to `loop.on_error` (loop continues)
- LLM errors return `"Error: {message}"` to the user
- Send failures trigger `loop.on_error`
- Message deduplication prevents processing the same message twice (capped at 1000 events, trimmed to 500)
