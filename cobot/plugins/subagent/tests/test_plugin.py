"""Tests for SubagentPlugin."""

import pytest
from unittest.mock import Mock

from ..plugin import SubagentPlugin, SubagentResult, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_subagent_plugin(self):
        assert isinstance(create_plugin(), SubagentPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "subagent"

    def test_capabilities(self):
        meta = create_plugin().meta
        assert "subagent" in meta.capabilities
        assert "tools" in meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 32

    def test_extension_points(self):
        meta = create_plugin().meta
        assert "subagent.before_spawn" in meta.extension_points
        assert "subagent.after_spawn" in meta.extension_points


# === Configuration ===


class TestConfigure:
    def test_defaults(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._max_concurrent == 3
        assert plugin._default_timeout == 300
        assert plugin._max_timeout == 1800

    def test_custom_values(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "subagent": {
                    "max_concurrent": 5,
                    "default_timeout_seconds": 600,
                    "max_timeout_seconds": 3600,
                }
            }
        )
        assert plugin._max_concurrent == 5
        assert plugin._default_timeout == 600
        assert plugin._max_timeout == 3600


# === Spawn ===


class TestSpawn:
    def _make_registry(self, llm=None):
        """Create a mock registry with proper get_implementations."""
        registry = Mock()
        registry.get_implementations.return_value = []
        registry.get_by_capability.return_value = llm
        return registry

    def _make_llm(self, response_text="done"):
        mock_llm = Mock()
        mock_response = Mock()
        mock_response.content = response_text
        mock_llm.chat = Mock(return_value=mock_response)
        return mock_llm

    @pytest.mark.asyncio
    async def test_spawn_no_llm(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=None)

        result = await plugin.spawn(task="test task")

        assert result.success is False
        assert "No LLM" in result.error

    @pytest.mark.asyncio
    async def test_spawn_success(self):
        mock_llm = self._make_llm("Task completed successfully")

        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=mock_llm)

        result = await plugin.spawn(task="do something")

        assert result.success is True
        assert "Task completed" in result.output
        assert result.elapsed_seconds >= 0

    @pytest.mark.asyncio
    async def test_spawn_concurrency_limit(self):
        plugin = create_plugin()
        plugin.configure({"subagent": {"max_concurrent": 1}})
        plugin._active_count = 1

        result = await plugin.spawn(task="blocked")

        assert result.success is False
        assert "Concurrency limit" in result.error

    @pytest.mark.asyncio
    async def test_spawn_decrements_count_on_success(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=self._make_llm())

        await plugin.spawn(task="test")
        assert plugin._active_count == 0

    @pytest.mark.asyncio
    async def test_spawn_decrements_count_on_failure(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=None)

        await plugin.spawn(task="fail")
        assert plugin._active_count == 0

    @pytest.mark.asyncio
    async def test_spawn_with_context(self):
        mock_llm = self._make_llm()

        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=mock_llm)

        result = await plugin.spawn(
            task="analyze",
            context={"data": "test"},
        )

        assert result.success is True
        call_args = mock_llm.chat.call_args[0][0]
        user_msg = call_args[1]["content"]
        assert "test" in user_msg

    @pytest.mark.asyncio
    async def test_spawn_with_system_prompt(self):
        mock_llm = self._make_llm()

        plugin = create_plugin()
        plugin.configure({})
        plugin._registry = self._make_registry(llm=mock_llm)

        await plugin.spawn(task="test", system_prompt="You are a tester")

        call_args = mock_llm.chat.call_args[0][0]
        assert call_args[0]["content"] == "You are a tester"

    @pytest.mark.asyncio
    async def test_spawn_clamps_timeout(self):
        plugin = create_plugin()
        plugin.configure({"subagent": {"max_timeout_seconds": 60}})
        plugin._registry = self._make_registry(llm=None)

        result = await plugin.spawn(task="test", timeout_seconds=99999)
        assert result.success is False


# === Build Prompt ===


class TestBuildPrompt:
    def test_task_only(self):
        plugin = create_plugin()
        prompt = plugin._build_prompt("do this", None)
        assert "do this" in prompt

    def test_with_dict_context(self):
        plugin = create_plugin()
        prompt = plugin._build_prompt("task", {"key": "value"})
        assert "key" in prompt
        assert "value" in prompt

    def test_with_string_context(self):
        plugin = create_plugin()
        prompt = plugin._build_prompt("task", "some context")
        assert "some context" in prompt


# === Tool Provider ===


class TestToolProvider:
    def test_get_definitions(self):
        plugin = create_plugin()
        defs = plugin.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "spawn_subagent"

    def test_unknown_tool(self):
        plugin = create_plugin()
        result = plugin.execute("nonexistent", {})
        assert "Unknown" in result


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


# === SubagentResult ===


class TestSubagentResult:
    def test_success_result(self):
        r = SubagentResult(
            success=True,
            output="done",
            task="test",
            elapsed_seconds=1.5,
        )
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = SubagentResult(
            success=False,
            output="",
            task="test",
            elapsed_seconds=0,
            error="timeout",
        )
        assert r.success is False
        assert r.error == "timeout"
