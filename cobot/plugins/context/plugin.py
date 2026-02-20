"""Context plugin - builds system prompts from extension point implementers.

Defines extension points:
- context.system_prompt: Plugins contribute to system prompt
- context.history: Plugins contribute conversation history

Priority: 18 (after soul, memory, etc.)
"""

import sys

from ..base import Plugin, PluginMeta


class ContextPlugin(Plugin):
    """Context builder plugin - collects prompt contributions."""

    meta = PluginMeta(
        id="context",
        version="1.0.0",
        dependencies=["config"],
        extension_points=[
            "context.system_prompt",  # Plugins add to system prompt
            "context.history",  # Plugins add conversation history
        ],
        priority=18,
    )

    def __init__(self):
        pass

    def configure(self, config: dict) -> None:
        """Store configuration."""
        self._config = config

    async def start(self) -> None:
        """Initialize context builder."""
        print("[Context] Ready", file=sys.stderr)

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def build_system_prompt(self) -> str:
        """Build system prompt from all implementers.

        Collects contributions from all plugins that implement
        context.system_prompt extension point.

        Returns:
            Combined system prompt string.
        """
        parts = []

        if self._registry:
            implementations = self._registry.get_implementations(
                "context.system_prompt"
            )
            for plugin_id, plugin, method_name in implementations:
                try:
                    method = getattr(plugin, method_name)
                    contribution = method()
                    if contribution:
                        parts.append(contribution)
                except Exception as e:
                    print(
                        f"[Context] Error getting prompt from {plugin_id}: {e}",
                        file=sys.stderr,
                    )

        return "\n\n".join(parts)

    def build_history(self) -> list[dict]:
        """Build conversation history from all implementers.

        Collects contributions from all plugins that implement
        context.history extension point.

        Returns:
            List of message dicts for conversation history.
        """
        history = []

        if self._registry:
            implementations = self._registry.get_implementations("context.history")
            for plugin_id, plugin, method_name in implementations:
                try:
                    method = getattr(plugin, method_name)
                    contribution = method()
                    if contribution:
                        history.extend(contribution)
                except Exception as e:
                    print(
                        f"[Context] Error getting history from {plugin_id}: {e}",
                        file=sys.stderr,
                    )

        return history


def create_plugin() -> ContextPlugin:
    """Factory function for plugin discovery."""
    return ContextPlugin()
