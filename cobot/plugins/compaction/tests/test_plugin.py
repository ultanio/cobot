"""Tests for CompactionPlugin."""

import pytest
from unittest.mock import Mock

from ..plugin import CompactionPlugin, create_plugin


class TestCreatePlugin:
    def test_returns_compaction_plugin(self):
        assert isinstance(create_plugin(), CompactionPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "compaction"

    def test_capabilities(self):
        assert "compaction" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 16

    def test_consumes_llm(self):
        assert "llm" in create_plugin().meta.consumes


class TestConfigure:
    def test_defaults(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._max_tokens == 12000
        assert plugin._target_recent_tokens == 4000
        assert plugin._chars_per_token == 4

    def test_custom_values(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "compaction": {
                    "max_tokens": 8000,
                    "target_recent_tokens": 2000,
                    "chars_per_token": 3,
                }
            }
        )
        assert plugin._max_tokens == 8000
        assert plugin._target_recent_tokens == 2000
        assert plugin._chars_per_token == 3


class TestEstimateTokens:
    def test_empty(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._estimate_tokens([]) == 0

    def test_estimates_correctly(self):
        plugin = create_plugin()
        plugin.configure({})  # 4 chars per token
        messages = [{"content": "a" * 100}]
        assert plugin._estimate_tokens(messages) == 25

    def test_multiple_messages(self):
        plugin = create_plugin()
        plugin.configure({})
        messages = [{"content": "a" * 40}, {"content": "b" * 60}]
        assert plugin._estimate_tokens(messages) == 25


class TestTransformHistory:
    @pytest.mark.asyncio
    async def test_short_history_unchanged(self):
        plugin = create_plugin()
        plugin.configure({})
        ctx = {"messages": [{"role": "user", "content": "hi"}]}
        result = await plugin.transform_history(ctx)
        assert result["messages"] == ctx["messages"]

    @pytest.mark.asyncio
    async def test_under_limit_unchanged(self):
        plugin = create_plugin()
        plugin.configure({"compaction": {"max_tokens": 99999}})
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
            {"role": "user", "content": "bye"},
        ]
        ctx = {"messages": messages}
        result = await plugin.transform_history(ctx)
        assert len(result["messages"]) == 4

    @pytest.mark.asyncio
    async def test_compacts_long_history(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "compaction": {
                    "max_tokens": 10,
                    "target_recent_tokens": 5,
                    "chars_per_token": 1,
                }
            }
        )
        # No LLM available — should use fallback summary
        plugin._registry = Mock()
        plugin._registry.get_by_capability.return_value = None

        messages = [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "a" * 50},
            {"role": "assistant", "content": "b" * 50},
            {"role": "user", "content": "c" * 50},
            {"role": "assistant", "content": "d" * 50},
            {"role": "user", "content": "recent question"},
        ]
        ctx = {"messages": messages}
        result = await plugin.transform_history(ctx)

        # Should be compacted — fewer messages
        assert len(result["messages"]) < len(messages)
        # System prompt should still be first
        assert result["messages"][0]["role"] == "system"
        # Should contain summary
        summary_msgs = [
            m for m in result["messages"] if "summary" in m.get("content", "").lower()
        ]
        assert len(summary_msgs) > 0


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start(self):
        plugin = create_plugin()
        await plugin.start()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()
