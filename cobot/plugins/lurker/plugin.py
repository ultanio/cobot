"""Lurker plugin - channel observation with pluggable sinks.

Lurker observes all messages (incoming and outgoing) on configured channels
by implementing session observer extension points. It never modifies the
message flow — pure observation.

It defines its own extension point (lurker.on_observe) so other plugins
can decide what to do with observed messages (index, search, analytics, etc.).

This is mechanism: lurker decides WHICH channels to observe and provides
the message stream. Sinks decide WHAT to do with messages.

Priority: 35 (after session and channels)
"""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..base import Plugin, PluginMeta
from ..communication import IncomingMessage, OutgoingMessage


class LurkerPlugin(Plugin):
    """Channel observer via session extension points.

    Implements:
      - session.on_receive: observe incoming messages
      - session.on_send: observe outgoing messages

    Defines:
      - lurker.on_observe: fired for each observed message (for sinks)

    Config:
        lurker:
          channels:
            - id: "-100123456789"
              name: "dev-chat"
            - id: "-100987654321"
              name: "announcements"
          sink: "jsonl"               # jsonl | markdown | none
          base_dir: "./lurker"
    """

    meta = PluginMeta(
        id="lurker",
        version="0.2.0",
        capabilities=["lurker"],
        dependencies=["session"],
        priority=35,  # After session (10) and channels (30)
        implements={
            "session.on_receive": "observe_incoming",
            "session.on_send": "observe_outgoing",
        },
        extension_points=[
            "lurker.on_observe",
        ],
    )

    def __init__(self):
        self._channels: dict[str, str] = {}  # channel_id -> name
        self._sink: str = "jsonl"
        self._base_dir: Path = Path("./lurker")
        self._registry = None
        self._counts: dict[str, int] = {}  # channel_id -> message count

    def configure(self, config: dict) -> None:
        """Configure lurker channels and default sink."""
        lurker_config = config.get("lurker", {})

        for ch in lurker_config.get("channels", []):
            ch_id = str(ch.get("id", ""))
            ch_name = ch.get("name", ch_id)
            if ch_id:
                self._channels[ch_id] = ch_name

        self._sink = lurker_config.get("sink", "jsonl")
        self._base_dir = Path(lurker_config.get("base_dir", "./lurker"))

    async def start(self) -> None:
        """Start lurker."""
        from ..registry import get_registry

        self._registry = get_registry()

        if self._channels:
            names = [f"{v} ({k})" for k, v in self._channels.items()]
            print(
                f"[Lurker] Observing {len(self._channels)} channels: "
                + ", ".join(names),
                file=sys.stderr,
            )
        else:
            print("[Lurker] No channels configured — lurking disabled", file=sys.stderr)

        if self._sink != "none":
            self._base_dir.mkdir(parents=True, exist_ok=True)
            print(f"[Lurker] Sink: {self._sink} → {self._base_dir}", file=sys.stderr)

    async def stop(self) -> None:
        """Report stats on shutdown."""
        if self._counts:
            total = sum(self._counts.values())
            print(f"[Lurker] Observed {total} messages total", file=sys.stderr)
            for ch_id, count in self._counts.items():
                name = self._channels.get(ch_id, ch_id)
                print(f"[Lurker]   {name}: {count}", file=sys.stderr)

    def is_lurked(self, channel_id: str) -> bool:
        """Check if a channel is in lurk mode."""
        return str(channel_id) in self._channels

    def _channel_name(self, channel_id: str, metadata: dict = None) -> str:
        """Get human name for a channel.

        Checks message metadata first (channel plugins may set group_name),
        falls back to lurker config, then raw channel_id.
        """
        if metadata:
            name = metadata.get("group_name")
            if name:
                return name
        return self._channels.get(str(channel_id), str(channel_id))

    # --- Session Observer Implementations ---

    def observe_incoming(self, msg: IncomingMessage) -> None:
        """Observe an incoming message (session.on_receive).

        Args:
            msg: Full IncomingMessage from the session layer.
        """
        if not self.is_lurked(msg.channel_id):
            return

        obs = {
            "direction": "incoming",
            "channel_id": msg.channel_id,
            "channel_type": msg.channel_type,
            "channel_name": self._channel_name(msg.channel_id, msg.metadata),
            "sender_id": msg.sender_id,
            "sender_name": msg.sender_name,
            "message": msg.content,
            "timestamp": msg.timestamp.isoformat()
            if isinstance(msg.timestamp, datetime)
            else str(msg.timestamp),
            "event_id": msg.id,
            "media": msg.media,
        }

        self._observe(obs)

    def observe_outgoing(self, msg: OutgoingMessage) -> None:
        """Observe an outgoing message (session.on_send).

        Args:
            msg: Full OutgoingMessage from the session layer.
        """
        if not self.is_lurked(msg.channel_id):
            return

        obs = {
            "direction": "outgoing",
            "channel_id": msg.channel_id,
            "channel_type": msg.channel_type,
            "channel_name": self._channel_name(msg.channel_id, msg.metadata),
            "sender_id": "self",
            "sender_name": "bot",
            "message": msg.content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_id": "",
            "media": msg.media,
        }

        self._observe(obs)

    def _observe(self, obs: dict) -> None:
        """Process an observation: count, fire extension points, write sink."""
        channel_id = obs["channel_id"]
        self._counts[channel_id] = self._counts.get(channel_id, 0) + 1

        # Fire extension point for other plugins (sinks, indexers, etc.)
        if self._registry:
            for _, plugin, method_name in self._registry.get_implementations(
                "lurker.on_observe"
            ):
                try:
                    method = getattr(plugin, method_name)
                    if asyncio.iscoroutinefunction(method):
                        # Lurker observers are sync (called from sync session methods),
                        # but handle async gracefully if needed in future
                        pass
                    else:
                        method(obs)
                except Exception as e:
                    print(f"[Lurker] Sink error: {e}", file=sys.stderr)

        # Built-in sink (if configured)
        if self._sink != "none":
            self._write_sink(obs)

    # --- Built-in sinks ---

    def _write_sink(self, obs: dict) -> None:
        """Write observation to built-in sink."""
        if self._sink == "jsonl":
            self._write_jsonl(obs)
        elif self._sink == "markdown":
            self._write_markdown(obs)

    def _day_dir(self) -> Path:
        """Get date-based directory."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._base_dir / date_str

    def _write_jsonl(self, obs: dict) -> None:
        """Write one JSONL line per message."""
        day_dir = self._day_dir()
        day_dir.mkdir(parents=True, exist_ok=True)

        filepath = day_dir / f"{obs['channel_id']}.jsonl"
        record = {
            "ts": obs["timestamp"],
            "direction": obs["direction"],
            "channel": obs["channel_id"],
            "channel_name": obs["channel_name"],
            "sender_id": obs["sender_id"],
            "sender": obs["sender_name"],
            "text": obs["message"],
            "event_id": obs["event_id"],
        }

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_markdown(self, obs: dict) -> None:
        """Write markdown-formatted log."""
        day_dir = self._day_dir()
        day_dir.mkdir(parents=True, exist_ok=True)

        filepath = day_dir / f"{obs['channel_id']}.md"
        ts = obs["timestamp"][:19].replace("T", " ")
        sender = obs["sender_name"] or obs["sender_id"]
        text = obs["message"]
        direction = obs["direction"]
        prefix = "→" if direction == "outgoing" else ""

        # Write header if new file
        if not filepath.exists():
            header = (
                f"# {obs['channel_name']} — "
                f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            )
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(header)

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"{prefix}**{sender}** ({ts}):\n{text}\n\n")

    # --- Setup Wizard ---

    def wizard_section(self) -> dict | None:
        return {
            "key": "lurker",
            "name": "Lurker",
            "description": "Passively observe channels without responding",
        }

    def wizard_configure(self, config: dict) -> dict:
        import click

        click.echo("\nLurker — passive channel observation")
        click.echo("Messages in lurked channels are logged, not responded to.\n")

        channels = []
        while True:
            if not click.confirm(
                "Add a channel to lurk?" if not channels else "Add another?",
                default=len(channels) == 0,
            ):
                break
            ch_id = click.prompt("Channel ID")
            ch_name = click.prompt("Channel name", default=ch_id)
            channels.append({"id": ch_id, "name": ch_name})

        sink = click.prompt(
            "Default sink",
            type=click.Choice(["jsonl", "markdown", "none"]),
            default="jsonl",
        )

        base_dir = click.prompt("Log directory", default="./lurker")

        return {
            "channels": channels,
            "sink": sink,
            "base_dir": base_dir,
        }


def create_plugin() -> LurkerPlugin:
    """Factory function for plugin discovery."""
    return LurkerPlugin()
