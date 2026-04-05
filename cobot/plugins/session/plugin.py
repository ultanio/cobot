"""Session plugin - orchestrates channel communication.

This plugin implements communication.* extension points and defines
session.* extension points for channel plugins to implement.

Extension points defined:
  Provider (channels implement these):
    - session.receive: Poll for messages
    - session.send: Send a message
    - session.typing: Show typing indicator
    - session.presence: Set status

  Observer (plugins implement these to watch message flow):
    - session.on_receive: Called for each incoming message after polling
    - session.on_send: Called after a message is successfully sent

Priority: 10 (after communication, before channels)
"""

from ..base import Plugin, PluginMeta
from ..communication import IncomingMessage, OutgoingMessage


class SessionPlugin(Plugin):
    """Session orchestrator - routes messages between channels and agent.

    Implements communication.* extension points (for agent to use).
    Defines session.* extension points:
      - Provider points (channels implement): session.receive, session.send, etc.
      - Observer points (plugins implement): session.on_receive, session.on_send
    """

    meta = PluginMeta(
        id="session",
        version="1.0.0",
        dependencies=["communication"],
        # Implement communication extension points
        implements={
            "communication.receive": "poll_all_channels",
            "communication.send": "send",
            "communication.typing": "typing",
            "communication.channels": "get_channels",
        },
        # Define session extension points
        extension_points=[
            # Provider points — channels implement these
            "session.receive",  # () -> list[IncomingMessage]
            "session.send",  # (OutgoingMessage) -> bool
            "session.typing",  # (channel_id: str) -> None
            "session.presence",  # (status: str) -> None
            # Observer points — plugins implement these to watch message flow
            "session.on_receive",  # (IncomingMessage) -> None
            "session.on_send",  # (OutgoingMessage) -> None
        ],
        priority=10,  # After communication (5), before channels (30)
    )

    def __init__(self):
        self._config = {}
        self._default_channel = None

    def configure(self, config: dict) -> None:
        """Configure session plugin."""
        self._config = config
        self._default_channel = config.get("default_channel")

    async def start(self) -> None:
        """Initialize session orchestrator."""
        self.log_info("Starting session orchestrator")
        self._log_channels()

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def _notify_observers(self, extension_point: str, message) -> None:
        """Notify all plugins implementing an observer extension point.

        Args:
            extension_point: "session.on_receive" or "session.on_send"
            message: IncomingMessage or OutgoingMessage
        """
        if not self._registry:
            return

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            extension_point
        ):
            try:
                method = getattr(plugin, method_name)
                method(message)
            except Exception as e:
                print(
                    f"[Session] Observer error ({plugin_id}.{method_name}): {e}",
                    file=sys.stderr,
                )

    def _log_channels(self) -> None:
        """Log discovered channels."""
        if not self._registry:
            return

        channels = []
        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.receive"
        ):
            channels.append(plugin_id)

        if channels:
            self.log_info(f"Channels: {', '.join(channels)}")
        else:
            self.log_warn("No channels registered")

    def poll_all_channels(self) -> list[IncomingMessage]:
        """Poll all channels for new messages.

        Calls session.receive on every channel that implements it.

        Returns:
            List of normalized IncomingMessage objects, sorted by timestamp
        """
        messages = []

        if not self._registry:
            return messages

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.receive"
        ):
            try:
                method = getattr(plugin, method_name)
                channel_messages = method()

                # Ensure channel_type is set, notify observers
                for msg in channel_messages:
                    if not msg.channel_type:
                        msg.channel_type = plugin_id
                    self._notify_observers("session.on_receive", msg)
                    messages.append(msg)

            except Exception as e:
                self.log_error(f"Error polling {plugin_id}: {e}")

        # Sort by timestamp
        messages.sort(key=lambda m: m.timestamp)
        return messages

    def send(self, message: OutgoingMessage) -> bool:
        """Send message to the appropriate channel.

        Routes to the channel matching message.channel_type.

        Args:
            message: OutgoingMessage with channel_type set

        Returns:
            True if sent successfully
        """
        if not self._registry:
            self.log_error("No registry available")
            return False

        channel_type = message.channel_type

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.send"
        ):
            if plugin_id == channel_type:
                try:
                    method = getattr(plugin, method_name)
                    result = method(message)
                    if result:
                        self._notify_observers("session.on_send", message)
                    return result
                except Exception as e:
                    self.log_error(f"Error sending via {plugin_id}: {e}")
                    return False

        self.log_warn(f"No channel found for type: {channel_type}")
        return False

    def typing(self, channel_type: str, channel_id: str) -> None:
        """Show typing indicator on a channel.

        Args:
            channel_type: Channel plugin id ("telegram", "discord", etc.)
            channel_id: Channel/group/room ID
        """
        if not self._registry:
            return

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.typing"
        ):
            if plugin_id == channel_type:
                try:
                    method = getattr(plugin, method_name)
                    method(channel_id)
                except Exception as e:
                    self.log_error(f"Error typing on {plugin_id}: {e}")
                return

    def presence(self, status: str) -> None:
        """Set presence status on all channels.

        Args:
            status: Status string ("online", "offline", "away", etc.)
        """
        if not self._registry:
            return

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.presence"
        ):
            try:
                method = getattr(plugin, method_name)
                method(status)
            except Exception as e:
                self.log_error(f"Error setting presence on {plugin_id}: {e}")

    def broadcast(self, content: str, exclude_channel: str = None) -> int:
        """Send message to all channels.

        Args:
            content: Message to broadcast
            exclude_channel: Optional channel to skip (avoid echo)

        Returns:
            Number of channels message was sent to
        """
        if not self._registry:
            return 0

        sent = 0
        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "session.send"
        ):
            if plugin_id == exclude_channel:
                continue

            try:
                # Get default channel_id from plugin
                channel_id = None
                if hasattr(plugin, "get_default_channel_id"):
                    channel_id = plugin.get_default_channel_id()

                if not channel_id:
                    continue

                message = OutgoingMessage(
                    channel_type=plugin_id,
                    channel_id=channel_id,
                    content=content,
                )

                method = getattr(plugin, method_name)
                if method(message):
                    sent += 1

            except Exception as e:
                self.log_error(f"Error broadcasting to {plugin_id}: {e}")

        return sent

    def get_channels(self) -> list[str]:
        """Get list of registered channel types.

        Returns:
            List of channel plugin IDs
        """
        if not self._registry:
            return []

        return [
            plugin_id
            for plugin_id, _, _ in self._registry.get_implementations("session.receive")
        ]


def create_plugin() -> SessionPlugin:
    """Factory function for plugin discovery."""
    return SessionPlugin()
