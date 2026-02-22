"""Memory plugin - defines extension points for memory storage.

This plugin defines the memory extension points that different
storage backends can implement (files, vector DB, etc.)

It also provides a "super tool" that aggregates results from
all implementations.

Priority: 12 (after workspace, before implementations)
"""

from typing import Optional

import click

from ..base import Plugin, PluginMeta


class MemoryPlugin(Plugin):
    """Memory extension point definer and aggregator."""

    meta = PluginMeta(
        id="memory",
        version="1.0.0",
        dependencies=["workspace"],
        extension_points=[
            "memory.store",  # Store a memory: store(key, content) -> None
            "memory.retrieve",  # Retrieve by key: retrieve(key) -> str
            "memory.search",  # Search memories: search(query) -> list[dict]
        ],
        implements={"cli.commands": "register_commands"},
        priority=12,
    )

    def __init__(self):
        self._registry = None

    def configure(self, config: dict) -> None:
        """Store configuration."""
        self._config = config

    async def start(self) -> None:
        """Initialize memory aggregator."""
        self.log_info("Ready (extension point definer)")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def store(self, key: str, content: str) -> None:
        """Store content using all implementations.

        Calls all plugins that implement memory.store.

        Args:
            key: Identifier for the memory
            content: Content to store
        """
        if not self._registry:
            return

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "memory.store"
        ):
            try:
                method = getattr(plugin, method_name)
                method(key, content)
            except Exception as e:
                self.log_error(f"Error storing via {plugin_id}: {e}")

    def retrieve(self, key: str) -> Optional[str]:
        """Retrieve content from first implementation that has it.

        Args:
            key: Identifier for the memory

        Returns:
            Content or None if not found
        """
        if not self._registry:
            return None

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "memory.retrieve"
        ):
            try:
                method = getattr(plugin, method_name)
                result = method(key)
                if result:
                    return result
            except Exception as e:
                self.log_error(f"Error retrieving via {plugin_id}: {e}")

        return None

    def search(self, query: str) -> list[dict]:
        """Search across all memory implementations.

        Aggregates results from all plugins that implement memory.search.

        Args:
            query: Search query

        Returns:
            List of results: [{"source": "plugin-id", "key": "...", "content": "...", "score": 0.9}]
        """
        results = []

        if not self._registry:
            return results

        for plugin_id, plugin, method_name in self._registry.get_implementations(
            "memory.search"
        ):
            try:
                method = getattr(plugin, method_name)
                impl_results = method(query)
                for r in impl_results:
                    r["source"] = plugin_id
                results.extend(impl_results)
            except Exception as e:
                self.log_error(f"Error searching via {plugin_id}: {e}")

        # Sort by score if available
        results.sort(key=lambda r: r.get("score", 0), reverse=True)
        return results

    def register_commands(self, cli):
        """Register memory CLI commands."""

        @cli.group()
        def memory():
            """Memory management commands."""
            pass

        @memory.command()
        @click.argument("key")
        @click.argument("content")
        def store(key: str, content: str):
            """Store content in memory.

            KEY: Identifier for the memory
            CONTENT: Content to store
            """
            self.store(key, content)
            click.echo(f"Stored: {key}")

        @memory.command()
        @click.argument("key")
        def get(key: str):
            """Retrieve content from memory.

            KEY: Identifier for the memory
            """
            content = self.retrieve(key)
            if content:
                click.echo(content)
            else:
                click.echo(f"Not found: {key}", err=True)

        @memory.command()
        @click.argument("query")
        def search(query: str):
            """Search memories.

            QUERY: Search string
            """
            results = self.search(query)
            if results:
                for r in results:
                    source = r.get("source", "unknown")
                    key = r.get("key", "?")
                    score = r.get("score", 0)
                    preview = r.get("content", "")[:100]
                    click.echo(f"[{source}] {key} (score: {score:.2f})")
                    click.echo(f"  {preview}...")
                    click.echo()
            else:
                click.echo("No results found.")

        @memory.command()
        def list():
            """List all memory keys."""
            if not self._registry:
                click.echo("Registry not available", err=True)
                return

            for plugin_id, plugin, method_name in self._registry.get_implementations(
                "memory.search"
            ):
                if hasattr(plugin, "list_keys"):
                    keys = plugin.list_keys()
                    click.echo(f"[{plugin_id}]")
                    for key in keys:
                        click.echo(f"  - {key}")


def create_plugin() -> MemoryPlugin:
    """Factory function for plugin discovery."""
    return MemoryPlugin()
