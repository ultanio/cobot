# Session Plugin

The session plugin **implements** `communication.*` extension points and **defines** `session.*` extension points for channel plugins.


## Table of Contents

- [Overview](#overview)
- [Extension Points](#extension-points)
- [Message Types](#message-types)
  - [IncomingMessage](#incomingmessage)
  - [OutgoingMessage](#outgoingmessage)
- [API](#api)
  - [poll_all_channels()](#pollallchannels)
  - [send(message)](#sendmessage)
  - [typing(channel_type, channel_id)](#typingchanneltype-channelid)
  - [broadcast(content, exclude_channel=None)](#broadcastcontent-excludechannelnone)
- [Implementing a Channel](#implementing-a-channel)
- [Polling vs Push Channels](#polling-vs-push-channels)
  - [Polling Channel](#polling-channel)
  - [Push Channel](#push-channel)
- [Agent Integration](#agent-integration)
- [Configuration](#configuration)
- [Priority](#priority)
- [Why This Design?](#why-this-design)

## Overview

```
                    ┌─────────┐
                    │  Agent  │
                    └────┬────┘
                         │
                  comm.poll() / comm.send()
                         │
               ┌─────────▼─────────┐
               │   Communication   │  ← defines extension points
               │      Plugin       │
               └─────────┬─────────┘
                         │
            implements communication.*
                         │
                    ┌────▼────┐
                    │ Session │  ← You are here
                    │ Plugin  │     implements comm.*, defines session.*
                    └────┬────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────▼────┐    ┌────▼────┐    ┌────▼────┐
    │Telegram │    │ Discord │    │  Nostr  │
    └─────────┘    └─────────┘    └─────────┘
         implements session.*
```

Session doesn't know about specific channels. It discovers them via extension points.

## Extension Points

Session defines these extension points for channels to implement:

| Extension Point | Signature | Description |
|-----------------|-----------|-------------|
| `session.receive` | `() -> list[IncomingMessage]` | Get new messages (poll or drain queue) |
| `session.send` | `(OutgoingMessage) -> bool` | Send a message |
| `session.typing` | `(channel_id: str) -> None` | Show typing indicator |
| `session.presence` | `(status: str) -> None` | Set online/offline status |
| `session.edit` | `(channel_id, msg_id, content) -> bool` | Edit a message |
| `session.delete` | `(channel_id, msg_id) -> bool` | Delete a message |
| `session.react` | `(channel_id, msg_id, emoji) -> bool` | Add reaction |

## Message Types

### IncomingMessage

Normalized message from any channel:

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
    media: list = None       # Attachments
    metadata: dict = None    # Channel-specific data
```

### OutgoingMessage

Message to send to a channel:

```python
@dataclass
class OutgoingMessage:
    channel_type: str        # Target channel type
    channel_id: str          # Target channel/group ID
    content: str             # Message text
    reply_to: str = None     # Message to reply to
    media: list = None       # Attachments
    metadata: dict = None    # Channel-specific options
```

## API

### poll_all_channels()

Get messages from all channels:

```python
messages = session.poll_all_channels()
for msg in messages:
    print(f"[{msg.channel_type}] {msg.sender_name}: {msg.content}")
```

Internally calls `session.receive` on every channel that implements it.

### send(message)

Send a message to a specific channel:

```python
session.send(OutgoingMessage(
    channel_type="telegram",
    channel_id="-1001234567890",
    content="Hello!",
    reply_to="123",  # Optional
))
```

Routes to the channel matching `channel_type`.

### typing(channel_type, channel_id)

Show typing indicator:

```python
session.typing("telegram", "-1001234567890")
```

### broadcast(content, exclude_channel=None)

Send to all channels:

```python
session.broadcast("System announcement!")
session.broadcast("Echo!", exclude_channel="telegram")  # Skip origin
```

## Implementing a Channel

Channels implement session extension points:

```python
from cobot.plugins.base import Plugin, PluginMeta
from cobot.plugins.session import IncomingMessage, OutgoingMessage


class MyChannelPlugin(Plugin):
    meta = PluginMeta(
        id="mychannel",
        version="1.0.0",
        dependencies=["session"],
        implements={
            "session.receive": "poll_messages",
            "session.send": "send_message",
            "session.typing": "send_typing",
        },
        priority=30,
    )

    def poll_messages(self) -> list[IncomingMessage]:
        """Called by session to get new messages."""
        # Return list of IncomingMessage
        ...

    def send_message(self, message: OutgoingMessage) -> bool:
        """Called by session to send a message."""
        # Send and return success
        ...

    def send_typing(self, channel_id: str) -> None:
        """Called by session to show typing."""
        ...
```

## Polling vs Push Channels

Session supports both patterns:

### Polling Channel

Actively fetches messages when `session.receive` is called:

```python
def poll_messages(self) -> list[IncomingMessage]:
    # Fetch from API
    response = self._client.get_updates()
    return [self._parse(msg) for msg in response]
```

Examples: Telegram (getUpdates), FileDrop (check inbox), RSS feeds

### Push Channel

Receives messages via webhook/websocket, queues them internally:

```python
def __init__(self):
    self._queue = Queue()

def start(self):
    # Webhook/websocket pushes to queue
    self._server = WebhookServer(on_message=self._queue.put)

def poll_messages(self) -> list[IncomingMessage]:
    # Drain the queue
    messages = []
    while not self._queue.empty():
        messages.append(self._queue.get_nowait())
    return messages
```

Examples: Discord (gateway), Slack (events API), Telegram (webhook mode)

The agent doesn't care which type - it just calls `session.poll_all_channels()`.

## Loop Integration

The loop plugin drives session via the communication layer:

```python
# The loop plugin (not agent.py) handles the poll → respond cycle:
#
# comm.poll() → session.poll_all_channels() → [telegram, discord, ...]
# comm.send() → session.send() → route to correct channel
#
# The agent is a minimal runner that asyncio.gather's all loop plugins.
# See the loop plugin README for the full pipeline.
```

## Configuration

```yaml
# cobot.yml
plugins:
  session:
    default_channel: telegram  # For broadcasts without target
    
  telegram:
    bot_token: ${TELEGRAM_BOT_TOKEN}
    groups:
      - id: -1001234567890
        name: "Main"
        
  discord:
    bot_token: ${DISCORD_BOT_TOKEN}
    guilds:
      - id: "123456789"
```

## Priority

Session loads early so channels can depend on it:

```
10 - session     (defines extension points)
20 - workspace   (provides paths)
30 - telegram    (implements session.*)
30 - discord     (implements session.*)
```

## Why This Design?

1. **Channel-agnostic core** - Agent never imports telegram/discord/etc
2. **Multi-channel** - One agent, many channels, same code
3. **Extensible** - Add channels without changing core
4. **Testable** - Mock session for agent tests
5. **Clean boundaries** - Each channel is its own package/repo
