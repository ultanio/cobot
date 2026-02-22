"""Plugin registry - central management of all plugins.

The registry handles:
- Plugin registration and validation
- Dependency resolution
- Configuration injection
- Lifecycle management (configure, start, stop)
- Lookup by ID or capability
- Hook execution

NOTE: As of v0.2.0, lifecycle methods (start, stop) and hooks are async.
"""

import sys
from typing import Optional, Type
from collections import defaultdict

from .base import Plugin, PluginMeta


class PluginError(Exception):
    """Error during plugin operations."""

    pass


class PluginRegistry:
    """Central registry for plugin management."""

    def __init__(self):
        self._plugins: dict[str, Plugin] = {}  # id -> instance
        self._capabilities: dict[str, list[str]] = defaultdict(
            list
        )  # capability -> [ids]
        self._load_order: list[str] = []  # Ordered list of plugin IDs
        self._started: bool = False

    def __len__(self) -> int:
        """Return number of registered plugins."""
        return len(self._plugins)

    def register(self, plugin_class: Type[Plugin]) -> Plugin:
        """Validate and register a plugin class.

        Args:
            plugin_class: Plugin class (not instance)

        Returns:
            Plugin instance

        Raises:
            PluginError: If plugin is invalid or already registered
        """
        # Validate it's a Plugin subclass
        if not isinstance(plugin_class, type) or not issubclass(plugin_class, Plugin):
            raise PluginError(
                f"Invalid plugin: {plugin_class} is not a Plugin subclass"
            )

        # Check for meta attribute
        if not hasattr(plugin_class, "meta") or not isinstance(
            plugin_class.meta, PluginMeta
        ):
            raise PluginError(
                f"Plugin {plugin_class.__name__} missing valid 'meta' attribute"
            )

        meta = plugin_class.meta

        # Check for duplicate ID
        if meta.id in self._plugins:
            raise PluginError(f"Plugin '{meta.id}' already registered")

        # Create instance
        try:
            instance = plugin_class()
        except Exception as e:
            raise PluginError(f"Failed to instantiate plugin '{meta.id}': {e}")

        # Register
        self._plugins[meta.id] = instance

        # Register capabilities
        for cap in meta.capabilities:
            self._capabilities[cap].append(meta.id)

        return instance

    def get(self, plugin_id: str) -> Optional[Plugin]:
        """Get plugin by ID.

        Args:
            plugin_id: Plugin identifier

        Returns:
            Plugin instance or None
        """
        return self._plugins.get(plugin_id)

    def get_by_capability(self, capability: str) -> Optional[Plugin]:
        """Get first plugin providing a capability.

        Returns the highest-priority (lowest number) plugin for the capability.

        Args:
            capability: Capability name (e.g., "llm", "communication")

        Returns:
            Plugin instance or None
        """
        plugin_ids = self._capabilities.get(capability, [])
        if not plugin_ids:
            return None

        # Return the first one (they're in registration order, which follows priority)
        return self._plugins.get(plugin_ids[0])

    def all_with_capability(self, capability: str) -> list[Plugin]:
        """Get all plugins providing a capability.

        Args:
            capability: Capability name

        Returns:
            List of plugin instances
        """
        plugin_ids = self._capabilities.get(capability, [])
        return [self._plugins[pid] for pid in plugin_ids if pid in self._plugins]

    def get_implementations(
        self, extension_point: str
    ) -> list[tuple[str, Plugin, str]]:
        """Find all plugins implementing an extension point.

        Looks at meta.implements dict for the extension point and returns
        the implementing plugins with their method names.

        Args:
            extension_point: Extension point name (e.g., "session.receive")

        Returns:
            List of (plugin_id, plugin_instance, method_name) tuples
        """
        implementations = []
        for plugin_id, plugin in self._plugins.items():
            if hasattr(plugin.meta, "implements") and plugin.meta.implements:
                method_name = plugin.meta.implements.get(extension_point)
                if method_name:
                    implementations.append((plugin_id, plugin, method_name))
        return implementations

    def all_plugins(self) -> list[Plugin]:
        """Get all registered plugins in load order."""
        return [self._plugins[pid] for pid in self._load_order]

    def _resolve_load_order(self) -> list[str]:
        """Resolve plugin load order based on priority and dependencies."""
        # Sort by priority first
        sorted_ids = sorted(
            self._plugins.keys(), key=lambda pid: self._plugins[pid].meta.priority
        )

        # TODO: Topological sort for dependencies
        # For now, just use priority order
        return sorted_ids

    def _check_dependencies(self) -> None:
        """Check that all plugin dependencies are satisfied."""
        for plugin_id, plugin in self._plugins.items():
            for dep in plugin.meta.dependencies:
                if dep not in self._plugins:
                    raise PluginError(
                        f"Plugin '{plugin_id}' depends on '{dep}' which is not registered"
                    )

    def configure_all(self, config: dict) -> None:
        """Inject configuration to all plugins.

        Each plugin receives the full config dict so it can access:
        - Its own section: config.get(plugin_id, {})
        - Shared settings: config.get("paths", {}), etc.

        Args:
            config: Full configuration dict (from cobot.yml)
        """
        self._load_order = self._resolve_load_order()
        self._check_dependencies()

        for plugin_id in self._load_order:
            plugin = self._plugins[plugin_id]
            # Pass full config - plugins extract what they need
            plugin_config = config

            try:
                plugin.configure(plugin_config)
            except Exception as e:
                print(
                    f"[Registry] Failed to configure '{plugin_id}': {e}",
                    file=sys.stderr,
                )
                raise PluginError(f"Configuration failed for '{plugin_id}': {e}")

    async def start_all(self) -> None:
        """Start all plugins in dependency order.

        Injects self as _registry into every plugin before starting,
        so plugins can use call_extension() without manual wiring.
        """
        if self._started:
            return

        # Auto-inject registry into all plugins
        for plugin in self._plugins.values():
            plugin._registry = self

        for plugin_id in self._load_order:
            plugin = self._plugins[plugin_id]

            try:
                await plugin.start()
            except Exception as e:
                print(f"[Registry] Failed to start '{plugin_id}': {e}", file=sys.stderr)
                raise PluginError(f"Start failed for '{plugin_id}': {e}")

        self._started = True

    async def stop_all(self) -> None:
        """Stop all plugins in reverse dependency order."""
        if not self._started:
            return

        for plugin_id in reversed(self._load_order):
            plugin = self._plugins[plugin_id]

            try:
                await plugin.stop()
            except Exception as e:
                print(f"[Registry] Error stopping '{plugin_id}': {e}", file=sys.stderr)

        self._started = False

    async def restart_all(self) -> None:
        """Restart all plugins (for event loop migration).

        Use when plugins were started in a different event loop and need
        their background tasks recreated in the current loop.
        """
        # Force restart even if already started
        self._started = False
        await self.start_all()

    async def run_hook(self, hook_name: str, ctx: dict) -> dict:
        """DEPRECATED: Use plugin.call_extension_chain() instead.

        Kept for backwards compatibility during migration.
        """
        print(
            f"[Registry] Warning: run_hook('{hook_name}') is deprecated. "
            "Use call_extension_chain() instead.",
            file=sys.stderr,
        )
        return ctx

    def list_plugins(self) -> list[dict]:
        """List all registered plugins with metadata.

        Returns:
            List of plugin info dicts
        """
        return [
            {
                "id": plugin.meta.id,
                "version": plugin.meta.version,
                "capabilities": plugin.meta.capabilities,
                "dependencies": plugin.meta.dependencies,
                "priority": plugin.meta.priority,
            }
            for plugin in self.all_plugins()
        ]


# Global registry instance
_registry: Optional[PluginRegistry] = None


def get_registry() -> PluginRegistry:
    """Get the global plugin registry."""
    global _registry
    if _registry is None:
        _registry = PluginRegistry()
    return _registry


def reset_registry() -> None:
    """Reset the global registry (for testing).

    Note: This is synchronous for test compatibility. If the registry
    was started, you should call `await registry.stop_all()` first.
    """
    global _registry
    if _registry:
        _registry._started = False  # Mark as stopped without async cleanup
    _registry = None


async def reset_registry_async() -> None:
    """Reset the global registry with proper async cleanup."""
    global _registry
    if _registry and _registry._started:
        await _registry.stop_all()
    _registry = None
