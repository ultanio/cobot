"""Tests for LoggerPlugin."""

import pytest

from ..plugin import LoggerPlugin, Colors, create_plugin


class TestCreatePlugin:
    def test_returns_logger_plugin(self):
        assert isinstance(create_plugin(), LoggerPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "logger"

    def test_capabilities(self):
        assert "logging" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 5

    def test_implements_hooks(self):
        meta = create_plugin().meta
        assert "loop.on_message" in meta.implements
        assert "loop.before_llm" in meta.implements
        assert "loop.after_llm" in meta.implements


class TestConfigure:
    def test_default_level(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._level == "info"

    def test_custom_level(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"level": "debug"}})
        assert plugin._level == "debug"

    def test_color_override(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        assert plugin._colors_enabled is False


class TestShouldLog:
    def test_info_at_info_level(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._should_log("info") is True

    def test_debug_at_info_level(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._should_log("debug") is False

    def test_error_at_info_level(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._should_log("error") is True

    def test_debug_at_debug_level(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"level": "debug"}})
        assert plugin._should_log("debug") is True

    def test_info_at_error_level(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"level": "error"}})
        assert plugin._should_log("info") is False


class TestLog:
    def test_log_writes_to_stderr(self, capsys):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        plugin._log("info", "test", "hello world")
        captured = capsys.readouterr()
        assert "hello world" in captured.err
        assert "[I]" in captured.err
        assert "test" in captured.err

    def test_log_respects_level(self, capsys):
        plugin = create_plugin()
        plugin.configure({"logger": {"level": "error", "color": False}})
        plugin._log("info", "test", "should not appear")
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_log_with_extras(self, capsys):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        plugin._log("info", "test", "msg", key="value")
        captured = capsys.readouterr()
        assert "value" in captured.err


class TestColorize:
    def test_no_color(self):
        plugin = create_plugin()
        plugin._colors_enabled = False
        assert plugin._colorize("I", "[I]") == "[I]"

    def test_with_color(self):
        plugin = create_plugin()
        plugin._colors_enabled = True
        result = plugin._colorize("I", "[I]")
        assert Colors.GREEN in result
        assert Colors.RESET in result


class TestExtensionPoints:
    @pytest.mark.asyncio
    async def test_log_message_received(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        ctx = {"message": "test message", "sender": "user1"}
        result = await plugin.log_message_received(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_log_before_llm(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"level": "debug", "color": False}})
        ctx = {
            "model": "gpt-4",
            "messages": [{"role": "system", "content": "You are helpful"}],
        }
        result = await plugin.log_before_llm(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_log_after_llm(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        ctx = {"tokens_in": 100, "tokens_out": 50}
        result = await plugin.log_after_llm(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_log_error(self):
        plugin = create_plugin()
        plugin.configure({"logger": {"color": False}})
        ctx = {"error": "something broke", "hook": "test_hook"}
        result = await plugin.log_error(ctx)
        assert result is ctx


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start(self):
        plugin = create_plugin()
        await plugin.start()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()
