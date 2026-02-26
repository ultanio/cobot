"""Tests for LoopPlugin and AggregatedToolProvider."""

from unittest.mock import Mock

import pytest

from ..plugin import LoopPlugin, AggregatedToolProvider, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_loop_plugin(self):
        assert isinstance(create_plugin(), LoopPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "loop"

    def test_capabilities(self):
        assert "loop" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 50

    def test_consumes(self):
        meta = create_plugin().meta
        assert "llm" in meta.consumes
        assert "tools" in meta.consumes

    def test_dependencies(self):
        meta = create_plugin().meta
        assert "communication" in meta.dependencies


# === Configuration ===


class TestConfigure:
    def test_configure_empty(self):
        plugin = create_plugin()
        plugin.configure({})

    def test_configure_with_loop_config(self):
        plugin = create_plugin()
        plugin.configure({"loop": {"poll_interval": 10}})


# === AggregatedToolProvider ===


class TestAggregatedToolProvider:
    def test_empty_providers(self):
        atp = AggregatedToolProvider([])
        assert atp.get_definitions() == []

    def test_aggregates_definitions(self):
        p1 = Mock()
        p1.get_definitions.return_value = [
            {"function": {"name": "tool_a"}, "type": "function"}
        ]
        p2 = Mock()
        p2.get_definitions.return_value = [
            {"function": {"name": "tool_b"}, "type": "function"}
        ]

        atp = AggregatedToolProvider([p1, p2])
        defs = atp.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_routes_execution(self):
        p1 = Mock()
        p1.get_definitions.return_value = [
            {"function": {"name": "tool_a"}, "type": "function"}
        ]
        p1.execute.return_value = "result_a"

        atp = AggregatedToolProvider([p1])
        result = atp.execute("tool_a", {"arg": "val"})
        assert result == "result_a"
        p1.execute.assert_called_once_with("tool_a", {"arg": "val"})

    def test_unknown_tool(self):
        atp = AggregatedToolProvider([])
        result = atp.execute("nonexistent", {})
        assert "Unknown" in result or "not found" in result.lower()

    def test_restart_requested_false(self):
        p1 = Mock()
        p1.get_definitions.return_value = []
        p1.restart_requested = False

        atp = AggregatedToolProvider([p1])
        assert atp.restart_requested is False

    def test_restart_requested_true(self):
        p1 = Mock()
        p1.get_definitions.return_value = []
        p1.restart_requested = True

        atp = AggregatedToolProvider([p1])
        assert atp.restart_requested is True

    def test_handles_provider_error(self):
        p1 = Mock()
        p1.get_definitions.side_effect = Exception("broken")

        atp = AggregatedToolProvider([p1])
        # Should not crash
        defs = atp.get_definitions()
        assert isinstance(defs, list)


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.start()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()
