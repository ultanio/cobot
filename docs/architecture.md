# Cobot Architecture

## Overview

```mermaid
graph TB
    subgraph "Agent Layer"
        A[Core Agent] --> R[Plugin Registry]
    end
    
    subgraph "Plugin System"
        R --> |"get_by_capability()"| P1[LLM Plugins]
        R --> |"get_by_capability()"| P2[Comm Plugins]
        R --> |"get_by_capability()"| P3[Tool Plugins]
        R --> |"get_by_capability()"| P4[Other Plugins]
    end
    
    subgraph "LLM Providers"
        P1 --> PPQ[ppq]
        P1 --> Ollama[ollama]
    end
    
    subgraph "Communication"
        P2 --> Nostr[nostr]
        P2 --> FileDrop[filedrop]
    end
    
    subgraph "Extension Points"
        FileDrop --> |"defines"| EP1[filedrop.before_write]
        FileDrop --> |"defines"| EP2[filedrop.after_read]
        FDN[filedrop-nostr] --> |"implements"| EP1
        FDN --> |"implements"| EP2
    end
```

## Plugin Registry

The registry is the heart of Cobot's plugin system.

```mermaid
classDiagram
    class PluginRegistry {
        -plugins: dict[str, Plugin]
        -capabilities: dict[str, list]
        -extension_points: dict[str, str]
        -implementations: dict[str, list]
        +register(plugin_class)
        +get(plugin_id) Plugin
        +get_by_capability(cap) Plugin
        +call_extension(point, ctx) dict
        +run_hook(hook_name, ctx) dict
    }
    
    class Plugin {
        +meta: PluginMeta
        +configure(config)
        +start()
        +stop()
        +call_extension(point, ctx)
    }
    
    class PluginMeta {
        +id: str
        +version: str
        +capabilities: list
        +dependencies: list
        +priority: int
        +extension_points: list
        +implements: dict
    }
    
    PluginRegistry "1" *-- "*" Plugin
    Plugin "1" *-- "1" PluginMeta
```

## Message Flow

```mermaid
sequenceDiagram
    participant U as User
    participant C as Communication
    participant A as Agent
    participant R as Registry
    participant L as LLM
    participant T as Tools
    
    U->>C: Send message
    C->>R: on_message_received(ctx)
    R->>A: Process message
    A->>R: get_by_capability("llm")
    R->>L: Return LLM plugin
    A->>L: Generate response
    L-->>A: Response (may include tool calls)
    
    opt Tool Calls
        A->>R: on_before_tool_exec(ctx)
        A->>T: Execute tool
        T-->>A: Tool result
        A->>R: on_after_tool_exec(ctx)
        A->>L: Continue with result
    end
    
    A->>R: transform_response(ctx)
    A->>C: Send response
    C->>U: Deliver message
```

## Extension Points

Extension points allow plugins to define hooks that other plugins can implement.

```mermaid
graph LR
    subgraph "Plugin A (defines)"
        A[PluginA] --> |"extension_points"| EP[point.name]
    end
    
    subgraph "Plugin B (implements)"
        B[PluginB] --> |"implements"| EP
        B --> M[handler_method]
    end
    
    subgraph "Execution"
        A --> |"call_extension()"| R[Registry]
        R --> |"invoke"| M
        M --> |"return ctx"| R
        R --> |"return ctx"| A
    end
```

### Example: FileDrop Signing

```mermaid
sequenceDiagram
    participant FD as FileDrop
    participant R as Registry
    participant FDN as FileDrop-Nostr
    
    Note over FD: Sending message
    FD->>R: call_extension("filedrop.before_write", ctx)
    R->>FDN: sign_message(ctx)
    FDN->>FDN: Sign with Schnorr
    FDN-->>R: ctx with signature
    R-->>FD: ctx with signature
    FD->>FD: Write signed message
    
    Note over FD: Receiving message
    FD->>FD: Read message
    FD->>R: call_extension("filedrop.after_read", ctx)
    R->>FDN: verify_message(ctx)
    FDN->>FDN: Verify Schnorr signature
    alt Valid signature
        FDN-->>R: ctx.verified = true
    else Invalid signature
        FDN-->>R: ctx.reject = true
    end
    R-->>FD: ctx
```

## Hook Chain

Plugins can intercept lifecycle events via hooks.

```mermaid
graph LR
    M[Message] --> H1[on_message_received]
    H1 --> H2[transform_system_prompt]
    H2 --> H3[transform_history]
    H3 --> H4[on_before_llm_call]
    H4 --> LLM[LLM Call]
    LLM --> H5[on_after_llm_call]
    H5 --> H6[on_before_tool_exec]
    H6 --> Tool[Tool Exec]
    Tool --> H7[on_after_tool_exec]
    H7 --> H8[transform_response]
    H8 --> H9[on_before_send]
    H9 --> Send[Send Response]
    Send --> H10[on_after_send]
```

## Plugin Loading

Plugins are loaded from multiple paths in order:

```mermaid
graph TB
    subgraph "Load Order"
        A[1. Core Plugins<br/>cobot/plugins/] --> R[Registry]
        B[2. System Plugins<br/>/opt/cobot/plugins/] --> R
        C[3. User Plugins<br/>~/.cobot/plugins/] --> R
        D[4. Project Plugins<br/>./plugins/] --> R
    end
    
    subgraph "Resolution"
        R --> |"First found wins"| P[Plugin Instance]
        R --> |"Topological sort"| O[Load Order]
        O --> |"By dependency"| P
    end
```

## Sovereignty Stack

```mermaid
graph TB
    subgraph "Physical Layer"
        HW[Your Hardware<br/>Pi, VPS, Laptop]
    end
    
    subgraph "Runtime Layer"
        HW --> CB[Cobot Runtime<br/>~2K lines Python]
    end
    
    subgraph "Identity Layer"
        CB --> NS[Nostr Identity<br/>npub/nsec]
    end
    
    subgraph "Economic Layer"
        CB --> LN[Lightning Wallet<br/>npub.cash]
    end
    
    subgraph "Intelligence Layer"
        CB --> LLM[LLM Provider<br/>PPQ, Ollama, etc.]
    end
    
    style HW fill:#22c55e
    style NS fill:#a855f7
    style LN fill:#f59e0b
```

## Scheduled Execution

Cobot supports scheduled and delegated execution through three composable plugins:

```mermaid
graph TB
    subgraph "Heartbeat"
        HB[heartbeat plugin] --> |"registers job"| CR
    end
    
    subgraph "Cron"
        CR[cron plugin] --> |"mode: isolated"| SA
        CR --> |"mode: main_session"| MS[Main Session]
    end
    
    subgraph "Subagent"
        SA[subagent plugin] --> |"spawn"| IS[Isolated Session]
        IS --> |"LLM call"| LLM[LLM Provider]
    end
```

### Subagent Plugin

Spawns isolated sessions for delegated work:
- No conversation history or memory context
- Tool: `spawn_subagent` for agent use
- API: `SubagentProvider.spawn()` for plugin use
- Extension points: `subagent.before_spawn`, `subagent.after_spawn`

### Cron Plugin

Schedules jobs with two execution modes:
- `isolated`: Spawns subagent (no context)
- `main_session`: Injects into main session (full context)
- Extension points: `cron.before_job`, `cron.after_job`

### Heartbeat Plugin

Convenience wrapper for periodic main session wake-up:
- Reads `HEARTBEAT.md` for instructions
- Uses cron internally with `mode: main_session`
- Supports quiet hours

```yaml
# Example configuration
subagent:
  max_concurrent: 3

cron:
  jobs:
    - name: daily-report
      schedule: "0 9 * * *"
      mode: isolated
      prompt: "Generate daily summary"

heartbeat:
  enabled: true
  interval_minutes: 15
  quiet_hours: "23:00-07:00"
```

## Directory Structure

```
cobot/
├── cobot/
│   ├── __init__.py
│   ├── agent.py          # Core agent loop
│   ├── cli.py            # CLI commands
│   └── plugins/
│       ├── __init__.py   # Plugin discovery
│       ├── base.py       # Plugin base class
│       ├── registry.py   # Plugin registry
│       ├── interfaces.py # Capability interfaces
│       ├── config/       # Configuration plugin
│       ├── ppq/          # PPQ LLM provider
│       ├── ollama/       # Ollama LLM provider
│       ├── nostr/        # Nostr communication
│       ├── filedrop/     # FileDrop communication
│       ├── wallet/       # Lightning wallet
│       ├── tools/        # Shell/file tools
│       ├── security/     # Prompt injection shield
│       ├── persistence/  # Conversation memory
│       ├── compaction/   # Context management
│       ├── logger/       # Logging
│       ├── knowledge/    # Local vector search
│       ├── subagent/     # Isolated session spawning
│       ├── cron/         # Scheduled job execution
│       └── heartbeat/    # Periodic main session wake-up
├── tests/                # Test suite
├── docs/                 # Documentation
├── cobot.yml.example     # Example config
├── SOUL.md.example       # Example system prompt
└── pyproject.toml        # Package config
```
