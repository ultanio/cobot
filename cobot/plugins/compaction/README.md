# Compaction Plugin

Summarizes old conversation history to stay within token limits.


## Table of Contents

- [Overview](#overview)
- [Priority](#priority)
- [Capabilities](#capabilities)
- [Dependencies](#dependencies)
- [Extension Points](#extension-points)
- [How It Works](#how-it-works)
- [Token Budget](#token-budget)
- [Configuration](#configuration)
- [Usage](#usage)
- [Summary Format](#summary-format)
- [Hooks](#hooks)
- [Preserving Important Info](#preserving-important-info)

## Overview

When conversation history gets too long, the compaction plugin summarizes older messages to free up context window space while preserving important information.

## Priority

**16** — After persistence.

## Capabilities

- `compaction` — History summarization

## Dependencies

- `config`
- `persistence` — Gets history to compact

## Extension Points

**Defines:** None  
**Implements:** None

## How It Works

```
Before compaction:
[msg1, msg2, msg3, ..., msg50, msg51, msg52]
                 ↓
After compaction:
[summary_of_msg1-50, msg51, msg52]
```

1. Estimate token count of history
2. If over budget, select older messages for summarization
3. Use LLM to generate summary
4. Replace old messages with summary
5. Keep recent messages intact

## Token Budget

```python
MAX_TOKENS = 12000         # Total context budget
TARGET_RECENT_TOKENS = 4000 # Keep this much for recent messages
CHARS_PER_TOKEN = 4        # Rough estimate
```

## Configuration

```yaml
# cobot.yml
compaction:
  max_tokens: 12000          # Total budget
  target_recent: 4000        # Recent messages budget
  summary_model: "gpt-4o-mini"  # Model for summarization
```

## Usage

Compaction is automatic via hooks, but can be triggered manually:

```python
# Get compaction plugin
compaction = registry.get("compaction")

# Check if compaction needed
if compaction.should_compact(messages):
    compacted = compaction.compact(messages)
```

## Summary Format

The summary is prefixed to indicate it's a summary:

```
[Previous conversation summary]
User asked about project Alpha. I explained the architecture and 
we discussed the timeline. User seemed satisfied with the plan.
---
```

## Extension Points

**Implements:**

| Extension Point | Method | Description |
|-----------------|--------|-------------|
| `loop.transform_history` | `transform_history` | Auto-compacts history if over token budget |

```python
async def transform_history(self, ctx: dict) -> dict:
    messages = ctx.get("messages", [])
    if self.should_compact(messages):
        ctx["messages"] = self.compact(messages)
    return ctx
```

## Preserving Important Info

The summarization prompt instructs the LLM to preserve:
- Key decisions and agreements
- Important facts mentioned
- User preferences
- Action items and commitments
