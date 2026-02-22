"""Starlette web server for the admin interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

try:
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, JSONResponse
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles
    from jinja2 import Environment, FileSystemLoader

    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

if TYPE_CHECKING:
    from starlette.requests import Request

    from .plugin import WebPlugin


class WebServer:
    """Starlette-based web server for the admin interface."""

    def __init__(self, host: str, port: int, plugin: WebPlugin) -> None:
        if not HAS_DEPS:
            raise RuntimeError(
                "Web dependencies not installed. "
                "Install with: pip install starlette uvicorn jinja2"
            )

        self.host = host
        self.port = port
        self.plugin = plugin
        self._shutdown_event = asyncio.Event()

        # Set up Jinja2 templates
        template_dir = Path(__file__).parent / "templates"
        self.templates = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=True,
        )

        # Build the Starlette app
        self.app = self._create_app()

    def _create_app(self) -> Starlette:
        """Create the Starlette application with routes."""
        static_dir = Path(__file__).parent / "static"

        routes = [
            Route("/", endpoint=self._index, methods=["GET"]),
            Route("/plugins", endpoint=self._plugins, methods=["GET"]),
            Route("/api/plugins", endpoint=self._api_plugins, methods=["GET"]),
            Route("/api/panels", endpoint=self._api_panels, methods=["GET"]),
        ]

        # Add routes contributed by other plugins via web.routes extension point
        for route_def in self.plugin.collect_routes():
            try:
                path = route_def.get("path", "/")
                method = route_def.get("method", "GET").upper()
                handler = route_def.get("handler")
                if handler and callable(handler):
                    routes.append(Route(path, endpoint=handler, methods=[method]))
            except Exception:
                pass  # Skip malformed route definitions

        # Only mount static files if the directory exists and has files
        if static_dir.exists() and any(static_dir.iterdir()):
            routes.append(
                Mount(
                    "/static", app=StaticFiles(directory=str(static_dir)), name="static"
                )
            )

        return Starlette(
            debug=False,
            routes=routes,
            on_startup=[self._on_startup],
            on_shutdown=[self._on_shutdown],
        )

    async def _on_startup(self) -> None:
        """Called when the server starts."""
        pass

    async def _on_shutdown(self) -> None:
        """Called when the server shuts down."""
        self._shutdown_event.set()

    def _render_template(self, name: str, **context) -> str:
        """Render a Jinja2 template."""
        # Add common context
        context["panels"] = self.plugin.collect_panels()
        template = self.templates.get_template(name)
        return template.render(**context)

    async def _index(self, request: Request) -> HTMLResponse:
        """Render the main admin page."""
        registry = self.plugin._registry

        # Gather overview data
        overview = {
            "plugin_count": len(registry) if registry else 0,
            "plugins": [],
        }

        if registry:
            for p in registry.all_plugins():
                overview["plugins"].append(
                    {
                        "id": p.meta.id,
                        "version": p.meta.version,
                        "priority": p.meta.priority,
                        "capabilities": p.meta.capabilities,
                    }
                )

        html = self._render_template("admin.html", overview=overview)
        return HTMLResponse(html)

    async def _plugins(self, request: Request) -> HTMLResponse:
        """Render the plugin graph page."""
        graph_data = self.plugin.get_plugin_graph_data()
        html = self._render_template(
            "plugins.html",
            graph_data=json.dumps(graph_data),
        )
        return HTMLResponse(html)

    async def _api_plugins(self, request: Request) -> JSONResponse:
        """API endpoint for plugin graph data."""
        graph_data = self.plugin.get_plugin_graph_data()
        return JSONResponse(graph_data)

    async def _api_panels(self, request: Request) -> JSONResponse:
        """API endpoint for available panels."""
        panels = self.plugin.collect_panels()
        return JSONResponse(panels)

    async def serve(self) -> None:
        """Run the server using uvicorn."""
        import uvicorn

        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        # Run until shutdown is requested
        await server.serve()

    async def shutdown(self) -> None:
        """Signal the server to shut down gracefully."""
        self._shutdown_event.set()
