# PPQ Plugin

LLM inference via [ppq.ai](https://ppq.ai).


## Table of Contents

- [Overview](#overview)
- [Priority](#priority)
- [Capabilities](#capabilities)
- [Dependencies](#dependencies)
- [Extension Points](#extension-points)
- [Configuration](#configuration)
- [Environment Variables](#environment-variables)
- [Usage](#usage)
- [Response Format](#response-format)
- [Errors](#errors)
- [Supported Models](#supported-models)

## Overview

Provides LLM capabilities using PPQ.ai's API. Pay-per-query with Bitcoin Lightning, no subscriptions.

## Priority

**20** — After config.

## Capabilities

- `llm` — Provides chat completion

## Dependencies

- `config` — Gets API key and model settings

## Extension Points

**Defines:** None  
**Implements:**

| Extension Point | Method | Description |
|-----------------|--------|-------------|
| `loop.before_llm` | `on_before_llm_call` | Pre-LLM logging/setup |
| `loop.after_llm` | `on_after_llm_call` | Post-LLM token tracking |

## Configuration

```yaml
# cobot.yml
provider: ppq  # Select this provider

ppq:
  api_key: "${PPQ_API_KEY}"    # Or set env var
  model: "gpt-4o"               # Default model
  api_base: "https://api.ppq.ai/v1"  # Optional override
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PPQ_API_KEY` | Your PPQ.ai API key |

## Usage

```python
# Get LLM provider
llm = registry.get_by_capability("llm")

# Simple chat
response = llm.chat([
    {"role": "system", "content": "You are helpful."},
    {"role": "user", "content": "Hello!"}
])
print(response.content)  # "Hi there!"

# With tools
response = llm.chat(messages, tools=tool_definitions)
if response.has_tool_calls:
    for call in response.tool_calls:
        print(call["function"]["name"])
```

## Response Format

```python
LLMResponse(
    content="Hello!",           # Response text
    tool_calls=[...],           # Tool calls (if any)
    model="gpt-4o",             # Model used
    usage={                     # Token usage
        "prompt_tokens": 10,
        "completion_tokens": 5
    }
)
```

## Errors

| Error | Description |
|-------|-------------|
| `InsufficientFundsError` | HTTP 402 - Need more credits |
| `LLMError` | General API errors |

## Supported Models

- `gpt-4o` — GPT-4 Omni
- `gpt-4o-mini` — Smaller, faster
- `gpt-5-nano` — Default, balanced
- `claude-3-opus` — Anthropic Claude
- See ppq.ai for full list
