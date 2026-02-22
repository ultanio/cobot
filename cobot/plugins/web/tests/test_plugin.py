"""Tests for the web plugin."""

import pytest

from cobot.plugins.config.plugin import ConfigPlugin
from cobot.plugins.registry import PluginRegistry
from cobot.plugins.web.plugin import WebPlugin, create_plugin


class TestWebPluginMeta:
    """Test WebPlugin metadata."""

    def test_meta_id(self):
        """Plugin has correct ID."""
        assert WebPlugin.meta.id == "web"

    def test_meta_version(self):
        """Plugin has version."""
        assert WebPlugin.meta.version == "1.0.0"

    def test_extension_points(self):
        """Plugin defines expected extension points."""
        assert "web.panels" in WebPlugin.meta.extension_points
        assert "web.routes" in WebPlugin.meta.extension_points
        assert "web.settings" in WebPlugin.meta.extension_points

    def test_dependencies(self):
        """Plugin has config dependency."""
        assert "config" in WebPlugin.meta.dependencies

    def test_implements_web_panels(self):
        """Plugin implements its own extension point."""
        assert "web.panels" in WebPlugin.meta.implements
        assert WebPlugin.meta.implements["web.panels"] == "get_builtin_panels"

    def test_priority(self):
        """Plugin has service layer priority."""
        assert WebPlugin.meta.priority == 30


class TestWebPluginConfiguration:
    """Test WebPlugin configuration."""

    def test_default_disabled(self):
        """Plugin is disabled by default."""
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._enabled is False

    def test_enable_via_config(self):
        """Plugin can be enabled via config."""
        plugin = create_plugin()
        plugin.configure({"web": {"enabled": True}})
        assert plugin._enabled is True

    def test_default_host(self):
        """Default host is localhost."""
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._host == "127.0.0.1"

    def test_custom_host(self):
        """Host can be configured."""
        plugin = create_plugin()
        plugin.configure({"web": {"host": "0.0.0.0"}})
        assert plugin._host == "0.0.0.0"

    def test_default_port(self):
        """Default port is 8080."""
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._port == 8080

    def test_custom_port(self):
        """Port can be configured."""
        plugin = create_plugin()
        plugin.configure({"web": {"port": 9000}})
        assert plugin._port == 9000


class TestBuiltinPanels:
    """Test built-in panel definitions."""

    def test_returns_list(self):
        """get_builtin_panels returns a list."""
        plugin = create_plugin()
        panels = plugin.get_builtin_panels()
        assert isinstance(panels, list)

    def test_has_plugins_panel(self):
        """Built-in panels include plugins panel."""
        plugin = create_plugin()
        panels = plugin.get_builtin_panels()
        panel_ids = [p["id"] for p in panels]
        assert "plugins" in panel_ids

    def test_has_overview_panel(self):
        """Built-in panels include overview panel."""
        plugin = create_plugin()
        panels = plugin.get_builtin_panels()
        panel_ids = [p["id"] for p in panels]
        assert "overview" in panel_ids

    def test_panel_structure(self):
        """Panels have required fields."""
        plugin = create_plugin()
        panels = plugin.get_builtin_panels()
        for panel in panels:
            assert "id" in panel
            assert "title" in panel
            assert "icon" in panel
            assert "route" in panel
            assert "priority" in panel


class TestPluginGraphData:
    """Test plugin graph data generation."""

    def test_empty_without_registry(self):
        """Returns empty data without registry."""
        plugin = create_plugin()
        data = plugin.get_plugin_graph_data()
        assert data == {"nodes": [], "edges": []}

    def test_with_registry(self):
        """Returns graph data with registry."""
        registry = PluginRegistry()
        registry.register(ConfigPlugin)
        registry.register(WebPlugin)
        # configure_all resolves load order
        registry.configure_all({})

        plugin = registry.get("web")
        plugin._registry = registry

        data = plugin.get_plugin_graph_data()

        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) >= 1

        # Find web plugin node
        web_node = next((n for n in data["nodes"] if n["id"] == "web"), None)
        assert web_node is not None
        assert web_node["version"] == "1.0.0"


class TestPanelCollection:
    """Test panel collection from extension points."""

    def test_collect_panels_without_registry(self):
        """Falls back to builtin panels without registry."""
        plugin = create_plugin()
        panels = plugin.collect_panels()
        # Should return builtin panels
        assert len(panels) >= 2

    def test_collect_panels_sorted_by_priority(self):
        """Panels are sorted by priority when registry is present."""
        registry = PluginRegistry()
        registry.register(ConfigPlugin)
        registry.register(WebPlugin)
        registry.configure_all({})

        plugin = registry.get("web")
        plugin._registry = registry

        panels = plugin.collect_panels()
        priorities = [p["priority"] for p in panels]
        assert priorities == sorted(priorities)


class TestRouteCollection:
    """Test route collection from extension points."""

    def test_collect_routes_without_registry(self):
        """Returns empty list without registry."""
        plugin = create_plugin()
        routes = plugin.collect_routes()
        assert routes == []

    def test_collect_routes_with_registry(self):
        """Collects routes from registry."""
        registry = PluginRegistry()
        registry.register(ConfigPlugin)
        registry.register(WebPlugin)
        registry.configure_all({})

        plugin = registry.get("web")
        plugin._registry = registry

        # WebPlugin doesn't implement web.routes itself, so empty
        routes = plugin.collect_routes()
        assert isinstance(routes, list)


class TestFactoryFunction:
    """Test the create_plugin factory."""

    def test_returns_web_plugin(self):
        """Factory returns WebPlugin instance."""
        plugin = create_plugin()
        assert isinstance(plugin, WebPlugin)

    def test_returns_new_instance(self):
        """Factory returns new instance each call."""
        p1 = create_plugin()
        p2 = create_plugin()
        assert p1 is not p2


@pytest.mark.asyncio
class TestLifecycle:
    """Test plugin lifecycle methods."""

    async def test_start_when_disabled(self):
        """Start does nothing when disabled."""
        plugin = create_plugin()
        plugin.configure({})  # Disabled by default
        await plugin.start()
        assert plugin._server is None

    async def test_stop_graceful(self):
        """Stop handles no server gracefully."""
        plugin = create_plugin()
        plugin.configure({})
        await plugin.stop()  # Should not raise
