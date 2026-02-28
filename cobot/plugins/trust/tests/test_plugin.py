"""Tests for trust context plugin."""

import pytest
from unittest.mock import MagicMock

from ..plugin import TrustPlugin, TRUST_PREAMBLE, create_plugin


@pytest.fixture
def plugin():
    """Create a configured trust plugin."""
    p = TrustPlugin()
    p._registry = MagicMock()
    p.configure({})
    return p


@pytest.fixture
def plugin_custom():
    """Create a trust plugin with custom config."""
    p = TrustPlugin()
    p._registry = MagicMock()
    p.configure(
        {
            "include_sender": True,
            "include_channel": True,
            "include_timestamp": False,
            "preamble": "Custom trust rule: always verify sender identity.",
        }
    )
    return p


class TestPluginMeta:
    """Test plugin metadata."""

    def test_id(self):
        assert TrustPlugin.meta.id == "trust"

    def test_priority(self):
        assert TrustPlugin.meta.priority == 16

    def test_dependencies(self):
        assert "config" in TrustPlugin.meta.dependencies

    def test_implements_hooks(self):
        impl = TrustPlugin.meta.implements
        assert "loop.transform_system_prompt" in impl
        assert "loop.on_message" in impl
        assert "loop.transform_history" in impl

    def test_create_plugin(self):
        p = create_plugin()
        assert isinstance(p, TrustPlugin)


class TestTransformPrompt:
    """Test system prompt transformation."""

    @pytest.mark.asyncio
    async def test_appends_trust_preamble(self, plugin):
        ctx = {"prompt": "You are Cobot."}
        result = await plugin.transform_prompt(ctx)
        assert TRUST_PREAMBLE in result["prompt"]
        assert result["prompt"].startswith("You are Cobot.")

    @pytest.mark.asyncio
    async def test_appends_custom_preamble(self, plugin_custom):
        ctx = {"prompt": "You are Cobot."}
        result = await plugin_custom.transform_prompt(ctx)
        assert TRUST_PREAMBLE in result["prompt"]
        assert "Custom trust rule" in result["prompt"]

    @pytest.mark.asyncio
    async def test_empty_prompt(self, plugin):
        ctx = {"prompt": ""}
        result = await plugin.transform_prompt(ctx)
        assert TRUST_PREAMBLE in result["prompt"]

    @pytest.mark.asyncio
    async def test_preserves_original_prompt(self, plugin):
        original = "You are Cobot, a helpful AI assistant."
        ctx = {"prompt": original}
        result = await plugin.transform_prompt(ctx)
        assert result["prompt"].startswith(original)


class TestCaptureMetadata:
    """Test metadata capture from incoming messages."""

    @pytest.mark.asyncio
    async def test_captures_full_metadata(self, plugin):
        ctx = {
            "message": "hello",
            "sender": "Zeus",
            "channel_type": "filedrop",
            "channel_id": "Zeus-inbox",
        }
        result = await plugin.capture_metadata(ctx)
        assert plugin._current_metadata is not None
        assert plugin._current_metadata["sender"] == "Zeus"
        assert plugin._current_metadata["channel"] == "filedrop"
        assert plugin._current_metadata["channel_id"] == "Zeus-inbox"
        assert "timestamp" in plugin._current_metadata
        # Passthrough — doesn't modify ctx
        assert result == ctx

    @pytest.mark.asyncio
    async def test_handles_missing_metadata(self, plugin):
        ctx = {"message": "hello"}
        await plugin.capture_metadata(ctx)
        assert plugin._current_metadata["sender"] == "unknown"
        assert plugin._current_metadata["channel"] == ""

    @pytest.mark.asyncio
    async def test_handles_partial_metadata(self, plugin):
        ctx = {"message": "hello", "sender": "k9ert"}
        await plugin.capture_metadata(ctx)
        assert plugin._current_metadata["sender"] == "k9ert"
        assert plugin._current_metadata["channel"] == ""


class TestInjectTrustedContext:
    """Test trusted context injection into message history."""

    @pytest.mark.asyncio
    async def test_injects_at_index_1(self, plugin):
        plugin._current_metadata = {
            "sender": "Zeus",
            "channel": "filedrop",
            "channel_id": "Zeus-inbox",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        messages = [
            {"role": "system", "content": "You are Cobot."},
            {"role": "user", "content": "hello"},
        ]
        ctx = {"messages": messages}
        result = await plugin.inject_trusted_context(ctx)

        assert len(result["messages"]) == 3
        assert result["messages"][0]["role"] == "system"  # soul
        assert result["messages"][1]["role"] == "system"  # trust context
        assert result["messages"][2]["role"] == "user"  # user message
        assert "Trusted Context" in result["messages"][1]["content"]
        assert "Zeus" in result["messages"][1]["content"]

    @pytest.mark.asyncio
    async def test_skips_when_no_metadata(self, plugin):
        messages = [
            {"role": "system", "content": "You are Cobot."},
            {"role": "user", "content": "hello"},
        ]
        ctx = {"messages": messages}
        result = await plugin.inject_trusted_context(ctx)
        assert len(result["messages"]) == 2  # unchanged

    @pytest.mark.asyncio
    async def test_skips_when_unknown_sender(self, plugin):
        plugin._current_metadata = {
            "sender": "unknown",
            "channel": "",
            "channel_id": "",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        ctx = {
            "messages": [
                {"role": "system", "content": "soul"},
                {"role": "user", "content": "hello"},
            ]
        }
        result = await plugin.inject_trusted_context(ctx)
        assert len(result["messages"]) == 2  # not injected

    @pytest.mark.asyncio
    async def test_resets_metadata_after_injection(self, plugin):
        plugin._current_metadata = {
            "sender": "Zeus",
            "channel": "filedrop",
            "channel_id": "",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        ctx = {
            "messages": [
                {"role": "system", "content": "soul"},
                {"role": "user", "content": "hello"},
            ]
        }
        await plugin.inject_trusted_context(ctx)
        assert plugin._current_metadata is None

    @pytest.mark.asyncio
    async def test_handles_empty_messages(self, plugin):
        plugin._current_metadata = {"sender": "Zeus", "channel": "filedrop"}
        ctx = {"messages": []}
        result = await plugin.inject_trusted_context(ctx)
        assert len(result["messages"]) == 0

    @pytest.mark.asyncio
    async def test_multi_turn_history(self, plugin):
        """Trust context goes at index 1, even with history."""
        plugin._current_metadata = {
            "sender": "k9ert",
            "channel": "telegram",
            "channel_id": "12345",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        messages = [
            {"role": "system", "content": "You are Cobot."},
            {"role": "user", "content": "earlier message"},
            {"role": "assistant", "content": "earlier reply"},
            {"role": "user", "content": "new message"},
        ]
        ctx = {"messages": messages}
        result = await plugin.inject_trusted_context(ctx)

        assert len(result["messages"]) == 5
        assert result["messages"][1]["role"] == "system"
        assert "Trusted Context" in result["messages"][1]["content"]
        assert "telegram" in result["messages"][1]["content"]


class TestBuildTrustedContext:
    """Test trusted context string building."""

    def test_full_context(self, plugin):
        meta = {
            "sender": "Zeus",
            "channel": "filedrop",
            "channel_id": "Zeus-inbox",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        result = plugin._build_trusted_context(meta)
        assert "Trusted Context" in result
        assert "filedrop:Zeus" in result
        assert "Channel: filedrop" in result
        assert "Timestamp: 2026-02-27T21:00:00Z" in result

    def test_sender_without_channel(self, plugin):
        meta = {"sender": "k9ert", "channel": "", "timestamp": "2026-02-27T21:00:00Z"}
        result = plugin._build_trusted_context(meta)
        assert "Sender: k9ert" in result
        assert "Channel:" not in result

    def test_respects_config_flags(self, plugin_custom):
        meta = {
            "sender": "Zeus",
            "channel": "filedrop",
            "channel_id": "Zeus-inbox",
            "timestamp": "2026-02-27T21:00:00Z",
        }
        result = plugin_custom._build_trusted_context(meta)
        assert "Sender:" in result
        assert "Channel:" in result
        assert "Timestamp:" not in result  # disabled in config
