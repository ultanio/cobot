"""FileDrop plugin - file-based communication fallback.

When Nostr relays are unreliable, use files in a shared directory.
Each agent has an inbox folder. Messages are JSON files.

Priority: 24 (just before nostr at 25, can be primary or fallback)
Capability: communication
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional
from datetime import datetime

from ..base import Plugin, PluginMeta
from ..communication import IncomingMessage
from ..interfaces import CommunicationProvider, Message, CommunicationError


class FileDropPlugin(Plugin, CommunicationProvider):
    """File-based communication plugin."""

    meta = PluginMeta(
        id="filedrop",
        version="1.0.0",
        capabilities=["communication"],
        dependencies=["config"],
        priority=24,  # Just before nostr
        implements={
            "session.poll_messages": "poll_inbox",
            "communication.send": "handle_send",
        },
    )

    def __init__(self):
        self._config: dict = {}
        self._base_dir: Path = Path("/tmp/filedrop")
        self._identity: str = "unknown"
        self._inbox: Optional[Path] = None
        self._processed: set[str] = set()

    def configure(self, config: dict) -> None:
        """Configure filedrop settings."""
        filedrop_config = config.get("filedrop", {})
        self._base_dir = Path(filedrop_config.get("base_dir", "/tmp/filedrop"))

        # Get identity from config or nostr section
        identity = config.get("identity", {})
        nostr_config = config.get("nostr", {})
        self._identity = (
            filedrop_config.get("identity")
            or identity.get("name")
            or nostr_config.get("npub", "")[:20]
            or "agent"
        )

    async def start(self) -> None:
        """Initialize directories."""
        # Create base directory if it doesn't exist
        self._base_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._base_dir, 0o777)  # World-writable for multi-agent
        except PermissionError:
            pass  # Already exists with different owner, that's fine

        # Create our inbox
        self._inbox = self._base_dir / self._identity / "inbox"
        self._inbox.mkdir(parents=True, exist_ok=True)

        # Create outbox for sent messages (for debugging)
        outbox = self._base_dir / self._identity / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)

        self.log_info(f"Inbox: {self._inbox}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    # --- CommunicationProvider Interface ---

    def get_identity(self) -> dict:
        """Get filedrop identity."""
        return {
            "name": self._identity,
            "inbox": str(self._inbox),
            "protocol": "filedrop",
        }

    def handle_send(self, message) -> bool:
        """Handle outgoing filedrop messages (implements communication.send)."""
        if message.channel_type != "filedrop":
            return False

        # Extract recipient from sender_id in metadata or channel_id
        recipient = message.metadata.get("recipient") if message.metadata else None
        if not recipient:
            # channel_id might be the inbox path — extract agent name
            channel_id = message.channel_id or ""
            if "/" in channel_id:
                # Path like /olymp/filedrop/Zeus/inbox — extract agent name
                parts = Path(channel_id).parts
                try:
                    idx = parts.index("inbox")
                    recipient = parts[idx - 1] if idx > 0 else None
                except (ValueError, IndexError):
                    pass
            else:
                recipient = channel_id

        if not recipient:
            self.log_error("Cannot send filedrop reply: no recipient found")
            return False

        self.log_debug(f"Sending filedrop reply to {recipient}")
        try:
            self.send(recipient, message.content)
            return True
        except Exception as e:
            self.log_error(f"Failed to send filedrop reply to {recipient}: {e}")
            return False

    def poll_inbox(self) -> list[IncomingMessage]:
        """Poll inbox for new messages (implements session.poll_messages)."""
        if not self._inbox or not self._inbox.exists():
            return []

        messages = []
        for msg_file in sorted(self._inbox.glob("*.json")):
            if msg_file.name in self._processed:
                continue

            try:
                with open(msg_file) as f:
                    data = json.load(f)

                sender = data.get("from", "unknown")
                subject = data.get("subject", "")
                content = data.get("content", "")
                body = f"[FileDrop from {sender}]"
                if subject:
                    body += f" Subject: {subject}"
                body += f"\n\n{content}"

                self.log_debug(f"Polled message from {sender}: {msg_file.name}")

                messages.append(
                    IncomingMessage(
                        id=data.get("id", msg_file.stem),
                        channel_type="filedrop",
                        channel_id=str(self._inbox),
                        sender_id=sender,
                        sender_name=sender,
                        content=body,
                        timestamp=datetime.fromtimestamp(
                            data.get("timestamp", msg_file.stat().st_mtime)
                        ),
                        metadata={"filedrop_file": msg_file.name},
                    )
                )

                self._processed.add(msg_file.name)

                # Move to processed folder
                processed_dir = self._inbox.parent / "processed"
                processed_dir.mkdir(exist_ok=True)
                msg_file.rename(processed_dir / msg_file.name)
                self.log_debug(f"Moved {msg_file.name} to processed")

            except Exception as e:
                self.log_error(f"Error reading {msg_file}: {e}")

        if messages:
            self.log_info(f"Polled {len(messages)} new message(s) from inbox")

        return messages

    def receive(self, since_minutes: int = 5) -> list[Message]:
        """Check inbox for new messages."""
        if not self._inbox or not self._inbox.exists():
            return []

        messages = []

        for msg_file in sorted(self._inbox.glob("*.json")):
            # Skip already processed
            if msg_file.name in self._processed:
                continue

            try:
                with open(msg_file) as f:
                    data = json.load(f)

                messages.append(
                    Message(
                        id=data.get("id", msg_file.stem),
                        sender=data.get("from", "unknown"),
                        content=data.get("content", ""),
                        timestamp=data.get("timestamp", int(msg_file.stat().st_mtime)),
                    )
                )

                # Mark as processed
                self._processed.add(msg_file.name)

                # Move to processed folder
                processed_dir = self._inbox.parent / "processed"
                processed_dir.mkdir(exist_ok=True)
                msg_file.rename(processed_dir / msg_file.name)

            except Exception as e:
                self.log_error(f"Error reading {msg_file}: {e}")

        return messages

    def send(self, recipient: str, message: str) -> str:
        """Send a message to another agent's inbox."""
        # Determine recipient inbox
        if "/" in recipient:
            # Full path provided
            recipient_inbox = Path(recipient)
        else:
            # Just name, use base_dir
            recipient_inbox = self._base_dir / recipient / "inbox"

        if not recipient_inbox.exists():
            # Try to create it
            try:
                recipient_inbox.mkdir(parents=True, exist_ok=True)
            except Exception:
                raise CommunicationError(
                    f"Recipient inbox not found: {recipient_inbox}"
                )

        # Create message
        msg_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
        msg_data = {
            "id": msg_id,
            "from": self._identity,
            "to": recipient,
            "content": message,
            "timestamp": int(time.time()),
            "sent_at": datetime.utcnow().isoformat() + "Z",
        }

        # Write to recipient's inbox
        msg_file = recipient_inbox / f"{msg_id}.json"
        with open(msg_file, "w") as f:
            json.dump(msg_data, f, indent=2)

        # Also save to our outbox for debugging
        if self._inbox:
            outbox = self._inbox.parent / "outbox"
            outbox.mkdir(exist_ok=True)
            with open(outbox / f"{msg_id}.json", "w") as f:
                json.dump(msg_data, f, indent=2)

        self.log_debug(f"Sent to {recipient}: {msg_id}")
        return msg_id


# Factory function
def create_plugin() -> FileDropPlugin:
    return FileDropPlugin()
