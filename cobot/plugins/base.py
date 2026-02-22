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
    optional_dependencies: list[str] = field(
        default_factory=list
    )  # Soft dependencies: use if loaded, skip if not
    consumes: list[str] = field(
        default_factory=list
    )  # Capability groups to aggregate from: ["storage"]
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
                self.log_error(f"Error in {pid}.{method_name}: {e}")
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
                self.log_error(f"Error in {pid}.{method_name}: {e}")
        return ctx

    # --- Logging Methods ---

    # Column width for source names (aligns log output)
    _LOG_SOURCE_WIDTH = 12

    def _log_fallback(self, level: str, msg: str) -> None:
        """Log with consistent format when logger plugin unavailable."""
        import os

        level_char = level[0].upper()
        use_color = (
            not os.environ.get("NO_COLOR")
            and hasattr(sys.stderr, "isatty")
            and sys.stderr.isatty()
        )
        if use_color:
            colors = {
                "I": "\033[32m",
                "W": "\033[33m",
                "E": "\033[31m",
                "D": "\033[90m",
            }
            reset = "\033[0m"
            color = colors.get(level_char, "")
            level_str = f"{color}[{level_char}]{reset}" if color else f"[{level_char}]"
        else:
            level_str = f"[{level_char}]"
        source = self.meta.id.ljust(self._LOG_SOURCE_WIDTH)[: self._LOG_SOURCE_WIDTH]
        print(f"{level_str} [{source}] {msg}", file=sys.stderr)

    def log(self, level: str, msg: str, **extra):
        """Log via the logger plugin if available."""
        if self._registry:
            logger = self._registry.get_by_capability("logging")
            if logger and hasattr(logger, "log"):
                logger.log(level, self.meta.id, msg, **extra)
                return
        # Fallback if no logger plugin - use consistent format
        self._log_fallback(level, msg)

    def log_debug(self, msg: str, **extra):
        self.log("debug", msg, **extra)

    def log_info(self, msg: str, **extra):
        self.log("info", msg, **extra)

    def log_warn(self, msg: str, **extra):
        self.log("warn", msg, **extra)

    def log_error(self, msg: str, **extra):
        self.log("error", msg, **extra)

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
