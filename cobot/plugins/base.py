"""Plugin base class and metadata.

All plugins must inherit from Plugin and define a PluginMeta.

NOTE: As of v0.3.0, hooks are replaced by extension points.
All inter-plugin communication uses call_extension().
"""

from __future__ import annotations

import asyncio
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import PluginRegistry


@dataclass
class PluginMeta:
    """Plugin metadata - defines identity and capabilities."""

    id: str  # Unique identifier: "ppq", "ollama", "nostr"
    version: str  # Semver: "1.0.0"
    capabilities: list[str] = field(default_factory=list)  # What it provides: ["llm"]
    dependencies: list[str] = field(
        default_factory=list
    )  # Required plugins: ["config"]
    priority: int = 50  # Load order (lower = earlier)
    extension_points: list[str] = field(
        default_factory=list
    )  # Extension points this plugin defines: ["context.system_prompt"]
    implements: dict[str, str] = field(
        default_factory=dict
    )  # Extension points this plugin implements: {"context.system_prompt": "get_soul"}

    def __post_init__(self):
        if not self.id:
            raise ValueError("Plugin id is required")
        if not self.version:
            raise ValueError("Plugin version is required")


class Plugin(ABC):
    """Base class for all plugins.

    Plugins must:
    1. Define a `meta` class attribute with PluginMeta
    2. Implement configure(), start(), stop()
    3. Optionally implement capability interfaces (LLMProvider, etc.)
    4. Use meta.implements to declare extension point implementations

    The registry is auto-injected as self._registry before start().
    Use self.call_extension() to invoke extension points defined by
    other plugins.

    Example:
        class MyPlugin(Plugin):
            meta = PluginMeta(
                id="myplugin",
                version="1.0.0",
                capabilities=["llm"],
                dependencies=["config"],
                priority=20,
                implements={
                    "loop.on_message": "handle_message",
                },
            )

            def configure(self, config: dict) -> None:
                self._config = config

            async def start(self) -> None:
                pass

            async def stop(self) -> None:
                pass

            async def handle_message(self, ctx: dict) -> dict:
                # Process message
                return ctx
    """

    meta: PluginMeta  # Must be defined by subclass
    _registry: PluginRegistry | None = None  # Auto-injected by registry

    def configure(self, config: dict) -> None:
        """Receive plugin-specific configuration.

        Called before start(). Config is the plugin's section from cobot.yml.
        This method is intentionally synchronous - config is just assignment.

        Args:
            config: Plugin-specific config dict (may be empty)
        """
        pass

    @abstractmethod
    async def start(self) -> None:
        """Initialize the plugin.

        Called after all plugins are configured, in dependency order.
        self._registry is available at this point.
        """
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Clean up plugin resources.

        Called on shutdown, in reverse dependency order.
        """
        pass

    # --- Extension Point Dispatch ---

    async def call_extension(self, point: str, ctx: dict | None = None) -> list:
        """Call all implementations of an extension point and collect results.

        Args:
            point: Extension point name (e.g., "context.system_prompt")
            ctx: Optional context dict to pass to each implementer

        Returns:
            List of non-None results from implementers
        """
        if not self._registry:
            return []
        results = []
        for pid, plugin, method_name in self._registry.get_implementations(point):
            try:
                method = getattr(plugin, method_name)
                if asyncio.iscoroutinefunction(method):
                    result = await method(ctx) if ctx is not None else await method()
                else:
                    result = method(ctx) if ctx is not None else method()
                if result is not None:
                    results.append(result)
            except Exception as e:
                print(
                    f"[{self.meta.id}] Error in {pid}.{method_name}: {e}",
                    file=sys.stderr,
                )
        return results

    async def call_extension_chain(self, point: str, ctx: dict) -> dict:
        """Call extension point implementations as a chain.

        Each implementer receives and returns ctx. If any sets
        ctx["abort"] = True, the chain stops.

        Args:
            point: Extension point name
            ctx: Context dict flowing through the chain

        Returns:
            Modified context dict
        """
        if not self._registry:
            return ctx
        for pid, plugin, method_name in self._registry.get_implementations(point):
            try:
                method = getattr(plugin, method_name)
                if asyncio.iscoroutinefunction(method):
                    result = await method(ctx)
                else:
                    result = method(ctx)
                if result is not None:
                    ctx = result
                if ctx.get("abort"):
                    break
            except Exception as e:
                print(
                    f"[{self.meta.id}] Error in {pid}.{method_name}: {e}",
                    file=sys.stderr,
                )
        return ctx

    # --- CLI Extension ---

    def register_commands(self, cli) -> None:
        """Register CLI commands.

        Called during CLI initialization. Plugins can add commands/groups
        to the main CLI.

        Args:
            cli: Click group (the main cobot CLI)
        """
        pass

    # --- Setup Wizard Extension ---

    def wizard_section(self) -> dict | None:
        """Return wizard section info for this plugin.

        Returns:
            dict with keys: key, name, description — or None to skip.
        """
        return None

    def wizard_configure(self, config: dict) -> dict:
        """Interactive configuration for the setup wizard.

        Args:
            config: Configuration dict built so far

        Returns:
            Configuration dict for this plugin's section
        """
        return {}


# Legacy hook names — kept for reference during migration.
# These are now extension points on the loop plugin.
HOOK_METHODS = [
    "loop.on_message",
    "loop.transform_system_prompt",
    "loop.transform_history",
    "loop.before_llm",
    "loop.after_llm",
    "loop.before_tool",
    "loop.after_tool",
    "loop.transform_response",
    "loop.before_send",
    "loop.after_send",
    "loop.on_error",
]
