# Web Admin Plugin

The web plugin provides an admin dashboard for Cobot with a plugin graph visualization.

## Extension Points

This plugin defines three extension points that other plugins can implement:

| Extension Point | Purpose |
|-----------------|---------|
| `web.panels` | Add entries to the sidebar navigation |
| `web.routes` | Add HTTP endpoints that serve content |
| `web.settings` | Add settings panels (future) |

**Key concept:** Panels are just navigation entries — to provide actual content, you also need to register a route.

## Route Prefixing

Routes are **auto-prefixed** with the plugin id to avoid collisions between plugins:

| Plugin ID | Declared Path | Actual URL |
|-----------|---------------|------------|
| `stats` | `dashboard` | `/stats/dashboard` |
| `wallet` | `balance` | `/wallet/balance` |
| `api` | `/health` | `/health` (absolute) |

- **Relative paths** (no leading `/`) are prefixed: `balance` → `/<plugin_id>/balance`
- **Absolute paths** (leading `/`) are kept as-is: `/health` → `/health`

Use relative paths unless you explicitly need a global route.

## Quick Start: Adding a Panel

A panel needs two things:
1. A **panel definition** (sidebar entry) via `web.panels`
2. A **route handler** (content) via `web.routes`

```python
from starlette.requests import Request
from starlette.responses import HTMLResponse

from cobot.plugins.base import Plugin, PluginMeta


class StatsPlugin(Plugin):
    meta = PluginMeta(
        id="stats",
        version="1.0.0",
        implements={
            "web.panels": "get_panels",
            "web.routes": "get_routes",
        },
    )

    def get_panels(self) -> list[dict]:
        """Register sidebar navigation entry."""
        return [
            {
                "id": "stats",
                "title": "Statistics",
                "icon": "📈",
                "route": "dashboard",  # → /stats/dashboard
                "priority": 50,
            }
        ]

    def get_routes(self) -> list[dict]:
        """Register route handler for panel content."""
        return [
            {
                "path": "dashboard",  # → /stats/dashboard
                "method": "GET",
                "handler": self.handle_stats,
            }
        ]

    async def handle_stats(self, request: Request) -> HTMLResponse:
        """Render the stats panel content."""
        html = """
        <h1>📈 Statistics</h1>
        <p>Your stats content here...</p>
        """
        return HTMLResponse(html)
```

## Panel Definition

```python
{
    "id": "unique-id",       # Unique identifier
    "title": "Panel Title",  # Displayed in sidebar
    "icon": "🎯",            # Emoji or icon class
    "route": "panel-path",   # Relative path (auto-prefixed with plugin id)
    "priority": 50,          # Sort order (lower = first)
}
```

## Route Definition

```python
{
    "path": "custom/path",       # Relative path (auto-prefixed with plugin id)
    "method": "GET",             # HTTP method (GET, POST, etc.)
    "handler": self.my_handler,  # Callable (method reference)
}
```

Handlers receive a Starlette `Request` and return a `Response`:

```python
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse

async def handle_page(self, request: Request) -> HTMLResponse:
    return HTMLResponse("<h1>Hello</h1>")

async def handle_api(self, request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "count": 42})
```

## Examples

### Example 1: Simple HTML Panel

```python
class HelloPlugin(Plugin):
    meta = PluginMeta(
        id="hello",
        version="1.0.0",
        implements={
            "web.panels": "get_panels",
            "web.routes": "get_routes",
        },
    )

    def get_panels(self) -> list[dict]:
        # route "index" → /hello/index
        return [{"id": "hello", "title": "Hello", "icon": "👋", "route": "index", "priority": 100}]

    def get_routes(self) -> list[dict]:
        # path "index" → /hello/index
        return [{"path": "index", "method": "GET", "handler": self.handle_hello}]

    async def handle_hello(self, request: Request) -> HTMLResponse:
        return HTMLResponse("<h1>👋 Hello from my plugin!</h1>")
```

### Example 2: JSON API Endpoint (No Panel)

Routes don't require a panel — use this for pure API endpoints:

```python
class ApiPlugin(Plugin):
    meta = PluginMeta(
        id="api",
        version="1.0.0",
        implements={"web.routes": "get_routes"},
    )

    def get_routes(self) -> list[dict]:
        return [
            # Relative paths → /api/health, /api/metrics
            {"path": "health", "method": "GET", "handler": self.health_check},
            {"path": "metrics", "method": "GET", "handler": self.get_metrics},
        ]

    async def health_check(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "healthy"})

    async def get_metrics(self, request: Request) -> JSONResponse:
        return JSONResponse({
            "uptime_seconds": 3600,
            "messages_processed": 150,
        })
```

### Example 3: Global Route (No Prefix)

Use an absolute path (leading `/`) to skip the plugin prefix:

```python
class HealthPlugin(Plugin):
    meta = PluginMeta(
        id="health",
        version="1.0.0",
        implements={"web.routes": "get_routes"},
    )

    def get_routes(self) -> list[dict]:
        return [
            # Absolute path → /healthz (no prefix)
            {"path": "/healthz", "method": "GET", "handler": self.healthz},
        ]

    async def healthz(self, request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})
```

### Example 4: Dynamic Content with Plugin State

```python
class WalletWebPlugin(Plugin):
    meta = PluginMeta(
        id="wallet-web",
        version="1.0.0",
        dependencies=["wallet"],
        implements={
            "web.panels": "get_panels",
            "web.routes": "get_routes",
        },
    )

    def get_panels(self) -> list[dict]:
        # route "overview" → /wallet-web/overview
        return [{"id": "wallet", "title": "Wallet", "icon": "💰", "route": "overview", "priority": 30}]

    def get_routes(self) -> list[dict]:
        return [{"path": "overview", "method": "GET", "handler": self.show_wallet}]

    async def show_wallet(self, request: Request) -> HTMLResponse:
        # Access another plugin via registry
        wallet = self._registry.get("wallet")
        balance = wallet.get_balance() if wallet else "N/A"
        
        html = f"""
        <h1>💰 Wallet</h1>
        <p>Balance: <strong>{balance} sats</strong></p>
        """
        return HTMLResponse(html)
```

## Configuration

```yaml
web:
  enabled: true
  host: "127.0.0.1"  # Localhost only by default
  port: 8080
```

## Built-in Panels

| Panel | Route | Description |
|-------|-------|-------------|
| Overview | `/` | System status and plugin list |
| Plugin Graph | `/plugins` | Interactive dependency visualization |

## Dependencies

Install with:

```bash
pip install starlette uvicorn jinja2
```

Or add to your `cobot[web]` extras.
