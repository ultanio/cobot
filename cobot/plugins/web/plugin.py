"""Web plugin - defines web.panels, web.routes, and web.settings extension points.

Other plugins can implement these extension points to contribute to the web admin:
- web.panels: Add panels to the admin dashboard
- web.routes: Add custom routes to the web server
- web.settings: Add settings panels
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from cobot.plugins.base import Plugin, PluginMeta

if TYPE_CHECKING:
    from .server import WebServer


class WebPlugin(Plugin):
    """Web admin plugin providing extension points for the admin interface.

    Plugins that want to contribute panels should:
    1. Implement a method returning panel definitions
    2. Declare implements={"web.panels": "get_panels"} in their PluginMeta

    Panel definition format:
        {
            "id": "unique-panel-id",
            "title": "Panel Title",
            "icon": "📊",  # emoji or icon class
            "template": "panel_template.html",  # or None for default
            "data_fn": "get_panel_data",  # method name to get data
            "priority": 50,  # lower = appears first
        }

    Route definition format:
        {
            "path": "custom/path",  # Relative path, auto-prefixed with /<plugin_id>/
            "method": "GET",  # or POST, etc.
            "handler": "handle_custom_route",  # method name
        }

    Route paths are auto-prefixed with the plugin id to avoid collisions:
        - "balance" -> "/<plugin_id>/balance"
        - "/health" -> "/health" (absolute paths starting with / are not prefixed)
    """

    meta = PluginMeta(
        id="web",
        version="1.0.0",
        extension_points=["web.panels", "web.routes", "web.settings"],
        dependencies=["config"],
        implements={"web.panels": "get_builtin_panels"},
        priority=30,  # Service plugin layer
    )

    def __init__(self) -> None:
        self._server: WebServer | None = None
        self._server_task: asyncio.Task | None = None
        self._enabled: bool = False
        self._host: str = "127.0.0.1"
        self._port: int = 8080

    def configure(self, config: dict) -> None:
        """Configure the web plugin from cobot.yml."""
        web_config = config.get("web", {})
        self._enabled = web_config.get("enabled", False)
        self._host = web_config.get("host", "127.0.0.1")
        self._port = web_config.get("port", 8080)

    async def start(self) -> None:
        """Start the web server if enabled."""
        if not self._enabled:
            self.log_info("Web admin disabled in config")
            return

        # Import here to avoid dependency issues when disabled
        from .server import WebServer

        self._server = WebServer(
            host=self._host,
            port=self._port,
            plugin=self,
        )
        self._server_task = asyncio.create_task(self._server.serve())
        self.log_info(f"Web admin started at http://{self._host}:{self._port}")

    async def stop(self) -> None:
        """Stop the web server gracefully."""
        if self._server:
            await self._server.shutdown()
            self._server = None

        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

        self.log_info("Web admin stopped")

    def get_builtin_panels(self) -> list[dict]:
        """Return built-in panels provided by the web plugin itself.

        This implements the web.panels extension point that we define,
        contributing the plugin graph panel.
        """
        return [
            {
                "id": "plugins",
                "title": "Plugin Graph",
                "icon": "🔌",
                "route": "/plugins",
                "priority": 10,
            },
            {
                "id": "overview",
                "title": "Overview",
                "icon": "📊",
                "route": "/",
                "priority": 0,
            },
        ]

    def collect_panels(self) -> list[dict]:
        """Collect all panels from plugins implementing web.panels.

        Uses registry.get_implementations() for proper extension point discovery.
        Panel routes are auto-prefixed with the plugin id (same as routes).
        """
        if not self._registry:
            return self.get_builtin_panels()

        panels = []
        for pid, plugin, method_name in self._registry.get_implementations(
            "web.panels"
        ):
            try:
                method = getattr(plugin, method_name)
                result = method()
                if result:
                    for panel in result:
                        # Auto-prefix relative routes with plugin id
                        route = panel.get("route", "")
                        if route and not route.startswith("/"):
                            panel["route"] = f"/{pid}/{route}"
                    panels.extend(result)
            except Exception as e:
                self.log_error(f"Error collecting panels from {pid}: {e}")

        # Sort by priority
        panels.sort(key=lambda p: p.get("priority", 50))
        return panels

    def collect_routes(self) -> list[dict]:
        """Collect all routes from plugins implementing web.routes.

        Routes are auto-prefixed with the plugin id to avoid collisions:
        - "balance" -> "/<plugin_id>/balance"
        - "/health" -> "/health" (absolute paths are not prefixed)
        """
        if not self._registry:
            return []

        routes = []
        for pid, plugin, method_name in self._registry.get_implementations(
            "web.routes"
        ):
            try:
                method = getattr(plugin, method_name)
                result = method()
                if result:
                    for route in result:
                        route["_plugin"] = plugin
                        route["_plugin_id"] = pid
                        # Auto-prefix relative paths with plugin id
                        path = route.get("path", "")
                        if not path.startswith("/"):
                            route["path"] = f"/{pid}/{path}"
                    routes.extend(result)
            except Exception as e:
                self.log_error(f"Error collecting routes from {pid}: {e}")

        return routes

    def get_plugin_graph_data(self) -> dict:
        """Generate data for the plugin graph visualization."""
        if not self._registry:
            return {"nodes": [], "edges": []}

        nodes = []
        edges = []

        for plugin in self._registry.all_plugins():
            meta = plugin.meta
            node = {
                "id": meta.id,
                "version": meta.version,
                "priority": meta.priority,
                "capabilities": meta.capabilities,
                "extension_points": meta.extension_points,
                "implements": list(meta.implements.keys()) if meta.implements else [],
            }
            nodes.append(node)

            # Hard dependencies
            for dep in meta.dependencies:
                edges.append(
                    {
                        "from": meta.id,
                        "to": dep,
                        "type": "dependency",
                        "style": "solid",
                    }
                )

            # Optional dependencies
            for dep in meta.optional_dependencies:
                edges.append(
                    {
                        "from": meta.id,
                        "to": dep,
                        "type": "optional",
                        "style": "dashed",
                    }
                )

            # Implements edges
            for ext_point in meta.implements.keys():
                # Find the plugin that defines this extension point
                for other in self._registry.all_plugins():
                    if ext_point in other.meta.extension_points:
                        edges.append(
                            {
                                "from": meta.id,
                                "to": other.meta.id,
                                "type": "implements",
                                "style": "dotted",
                                "label": ext_point,
                            }
                        )
                        break

        return {"nodes": nodes, "edges": edges}


def create_plugin() -> WebPlugin:
    """Factory function for plugin instantiation."""
    return WebPlugin()
