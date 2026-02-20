# Communication Plugin

The communication plugin defines **extension points** for messaging. It's the abstraction layer between the agent and channel implementations.


## Table of Contents

- [Overview](#overview)
- [Extension Points](#extension-points)
- [Message Types](#message-types)
  - [IncomingMessage](#incomingmessage)
  - [OutgoingMessage](#outgoingmessage)
- [Agent Usage](#agent-usage)
- [Implementing Communication](#implementing-communication)
- [Why This Layer?](#why-this-layer)
- [Priority](#priority)

## Overview

```
┌─────────────────────────────────────────────────────────────┐
│                         Agent                               │
│                                                             │
│   comm.poll()         # Get messages                        │
│   comm.send(msg)      # Send message                        │
│   comm.typing(...)    # Show typing                         │
│   comm.get_channels() # List channels                       │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   Communication Plugin                      │
│                                                             │
│   Defines extension points:                                 │
│   - communication.receive                                   │
│   - communication.send                                      │
│   - communication.typing                                    │
│   - communication.channels                                  │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Session    │  ← implements communication.*
                    │    Plugin     │
                    └───────────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
         [Telegram]    [Discord]     [Nostr]
```

## Extension Points

| Extension Point | Signature | Description |
|-----------------|-----------|-------------|
| `communication.receive` | `() -> list[IncomingMessage]` | Poll for new messages |
| `communication.send` | `(OutgoingMessage) -> bool` | Send a message |
| `communication.typing` | `(channel_type, channel_id) -> None` | Show typing indicator |
| `communication.channels` | `() -> list[str]` | Get available channel types |

## Message Types

### IncomingMessage

```python
@dataclass
class IncomingMessage:
    id: str                  # Unique message ID
    channel_type: str        # "telegram", "discord", etc.
    channel_id: str          # Group/channel/room ID
    sender_id: str           # User ID
    sender_name: str         # Display name
    content: str             # Message text
    timestamp: datetime      # When sent
    reply_to: str = None     # ID of message being replied to
    media: list = []         # Attachments
    metadata: dict = {}      # Channel-specific data
```

### OutgoingMessage

```python
@dataclass
class OutgoingMessage:
    channel_type: str        # Target channel type
    channel_id: str          # Target channel/group ID
    content: str             # Message text
    reply_to: str = None     # Message to reply to
    media: list = []         # Attachments
    metadata: dict = {}      # Channel-specific options
```

## Usage

The loop plugin drives communication — the agent itself is a minimal runner:

```python
# In the loop plugin (not agent.py)
comm = registry.get("communication")

# Poll all channels
messages = comm.poll()
for msg in messages:
    comm.typing(msg.channel_type, msg.channel_id)
    response = await self._respond(msg.content)
    comm.send(OutgoingMessage(
        channel_type=msg.channel_type,
        channel_id=msg.channel_id,
        content=response,
        reply_to=msg.id,
    ))

# Get available channels
channels = comm.get_channels()  # ["telegram", "discord"]
```

## Implementing Communication

To provide communication, implement the extension points:

```python
class MyImplementation(Plugin):
    meta = PluginMeta(
        id="my-impl",
        implements={
            "communication.receive": "poll",
            "communication.send": "send",
            "communication.typing": "typing",
            "communication.channels": "get_channels",
        },
    )

    def poll(self) -> list[IncomingMessage]:
        # Return messages from your source
        ...

    def send(self, message: OutgoingMessage) -> bool:
        # Send and return success
        ...

    def typing(self, channel_type: str, channel_id: str) -> None:
        # Show typing indicator
        ...

    def get_channels(self) -> list[str]:
        # Return channel types you handle
        ...
```

## Why This Layer?

1. **Agent doesn't know about session** — Just uses communication
2. **Swappable implementations** — Session is one way to implement comm
3. **Clean interfaces** — Message types defined once, used everywhere
4. **Testable** — Mock communication for agent tests

## Priority

```
5  - communication  (defines extension points)
10 - session        (implements communication.*)
30 - telegram       (implements session.*)
30 - discord        (implements session.*)
```
