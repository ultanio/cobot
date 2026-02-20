"""Communication plugin - defines extension points for messaging.

This plugin defines the communication extension points. Implementations
like the session plugin provide the actual channel routing.

Priority: 5 (early - before implementations)
"""

import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..base import Plugin, PluginMeta


@dataclass
class IncomingMessage:
    """Normalized message from any channel."""

    id: str  # Unique message ID
    channel_type: str  # "telegram", "discord", etc.
    channel_id: str  # Group/channel/room ID
    sender_id: str  # User ID
    sender_name: str  # Display name
    content: str  # Message text
    timestamp: datetime  # When sent
    reply_to: Optional[str] = None  # ID of message being replied to
    media: list = field(default_factory=list)  # Attachments
    metadata: dict = field(default_factory=dict)  # Channel-specific data


@dataclass
class OutgoingMessage:
    """Message to send to a channel."""

    channel_type: str  # Target channel type
    channel_id: str  # Target channel/group ID
    content: str  # Message text
    reply_to: Optional[str] = None  # Message to reply to
    media: list = field(default_factory=list)  # Attachments
    metadata: dict = field(default_factory=dict)  # Channel-specific options


class CommunicationPlugin(Plugin):
    """Communication extension point definer and aggregator.

    Defines extension points:
    - communication.receive: Poll for incoming messages
    - communication.send: Send a message
    - communication.typing: Show typing indicator
    - communication.channels: Get available channels

    Implementations (like session plugin) register to provide these.
    """

    meta = PluginMeta(
        id="communication",
        version="1.0.0",
        extension_points=[
            "communication.receive",  # () -> list[IncomingMessage]
            "communication.send",  # (OutgoingMessage) -> bool
            "communication.typing",  # (channel_type, channel_id) -> None
            "communication.channels",  # () -> list[str]
        ],
        priority=5,  # Very early - before session
    )

    def __init__(self):
        self._config = {}

    def configure(self, config: dict) -> None:
        """Store configuration."""
        self._config = config

    async def start(self) -> None:
        """Initialize communication aggregator."""
        print("[Communication] Ready (extension point definer)", file=sys.stderr)

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def poll(self) -> list[IncomingMessage]:
        """Poll for messages from all implementations.

        Calls all plugins that implement communication.receive.

        Returns:
            List of IncomingMessage objects, sorted by timestamp
        """
        messages = []

        if not self._registry:
            return messages

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "communication.receive"
        ):
            try:
                method = getattr(plugin, method_name)
                impl_messages = method()
                messages.extend(impl_messages)
            except Exception as e:
                print(
                    f"[Communication] Error polling via {plugin_id}: {e}",
                    file=sys.stderr,
                )

        # Sort by timestamp
        messages.sort(key=lambda m: m.timestamp)
        return messages

    def send(self, message: OutgoingMessage) -> bool:
        """Send message via the appropriate implementation.

        Calls the first implementation that can handle this channel_type.

        Args:
            message: OutgoingMessage with channel_type set

        Returns:
            True if sent successfully
        """
        if not self._registry:
            print("[Communication] No registry available", file=sys.stderr)
            return False

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "communication.send"
        ):
            try:
                method = getattr(plugin, method_name)
                result = method(message)
                if result:
                    return True
            except Exception as e:
                print(
                    f"[Communication] Error sending via {plugin_id}: {e}",
                    file=sys.stderr,
                )

        print(
            f"[Communication] No implementation handled channel: {message.channel_type}",
            file=sys.stderr,
        )
        return False

    def typing(self, channel_type: str, channel_id: str) -> None:
        """Show typing indicator via the appropriate implementation.

        Args:
            channel_type: Channel plugin id ("telegram", "discord", etc.)
            channel_id: Channel/group/room ID
        """
        if not self._registry:
            return

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "communication.typing"
        ):
            try:
                method = getattr(plugin, method_name)
                method(channel_type, channel_id)
                return  # First implementation that handles it
            except Exception as e:
                print(
                    f"[Communication] Error typing via {plugin_id}: {e}",
                    file=sys.stderr,
                )

    def get_channels(self) -> list[str]:
        """Get list of available channel types.

        Returns:
            List of channel type strings
        """
        channels = []

        if not self._registry:
            return channels

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "communication.channels"
        ):
            try:
                method = getattr(plugin, method_name)
                impl_channels = method()
                channels.extend(impl_channels)
            except Exception as e:
                print(
                    f"[Communication] Error getting channels from {plugin_id}: {e}",
                    file=sys.stderr,
                )

        return list(set(channels))  # Dedupe


def create_plugin() -> CommunicationPlugin:
    """Factory function for plugin discovery."""
    return CommunicationPlugin()
