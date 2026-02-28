"""Tests for Cobot agent and LoopPlugin.

Cobot is now a minimal loop runner. All message handling, LLM calls,
and tool execution live in LoopPlugin. Tests are split accordingly.
"""

import asyncio
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, AsyncMock

import pytest

from cobot.agent import Cobot
from cobot.plugins import (
    PluginRegistry,
    reset_registry,
    LLMResponse,
    LLMError,
)
from cobot.plugins.communication import IncomingMessage, OutgoingMessage
from cobot.plugins.loop.plugin import LoopPlugin


@pytest.fixture(autouse=True)
def reset_plugins():
    """Reset plugin registry before each test."""
    reset_registry()
    yield
    reset_registry()


@pytest.fixture
def mock_registry():
    """Create a mock registry with basic plugins."""
    registry = Mock(spec=PluginRegistry)

    # Mock config plugin
    config_plugin = Mock()
    config_plugin.get_config.return_value = Mock(
        soul_path=Path("/nonexistent/SOUL.md"),
        polling_interval=30,
        provider="ppq",
    )

    # Mock LLM plugin
    llm_plugin = Mock()
    llm_plugin.chat.return_value = LLMResponse(content="Hello human!", model="test")

    # Mock communication plugin
    comm_plugin = Mock()
    comm_plugin.poll.return_value = []
    comm_plugin.send.return_value = True
    comm_plugin.typing.return_value = None
    comm_plugin.get_channels.return_value = ["telegram"]

    # Mock tools plugin
    tools_plugin = Mock()
    tools_plugin.get_definitions.return_value = []
    tools_plugin.restart_requested = False

    def get_plugin(name):
        plugins = {
            "config": config_plugin,
            "communication": comm_plugin,
        }
        return plugins.get(name)

    def get_by_capability(cap):
        caps = {
            "llm": llm_plugin,
            "tools": tools_plugin,
        }
        return caps.get(cap)

    def all_with_cap(cap):
        if cap == "loop":
            return []
        if cap == "tools":
            return [tools_plugin]
        return []

    registry.get = get_plugin
    registry.get_by_capability = get_by_capability
    registry.all_with_capability = all_with_cap
    registry.list_plugins.return_value = []
    registry.stop_all = AsyncMock()
    registry.run_hook = AsyncMock(side_effect=lambda hook, ctx: ctx)
    registry.get_implementations = Mock(
        return_value=[]
    )  # No extension point implementations

    return registry


def _make_loop(mock_registry) -> LoopPlugin:
    """Create a LoopPlugin wired to mock registry."""
    loop = LoopPlugin()
    loop._registry = mock_registry
    # Stub extension chain to pass-through (no plugins implementing points)
    loop.call_extension_chain = AsyncMock(side_effect=lambda point, ctx: ctx)
    return loop


class TestCobot:
    """Test minimal Cobot loop runner."""

    def test_init(self, mock_registry):
        """Should initialize with registry."""
        bot = Cobot(mock_registry)
        assert bot.registry == mock_registry

    def test_run_no_loops(self, mock_registry):
        """Should exit gracefully when no loop plugins registered."""
        bot = Cobot(mock_registry)
        asyncio.run(bot.run())
        # Should not crash


class TestLoopPlugin:
    """Test LoopPlugin message handling."""

    def test_load_soul_exists(self, mock_registry):
        """Should load SOUL.md if it exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            soul_path = Path(tmpdir) / "SOUL.md"
            soul_path.write_text("I am TestBot!")

            config_plugin = mock_registry.get("config")
            config_plugin.get_config.return_value.soul_path = soul_path

            loop = _make_loop(mock_registry)
            asyncio.run(loop.start())

            assert loop._soul == "I am TestBot!"

    def test_load_soul_missing(self, mock_registry):
        """Should use default soul if file missing."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        assert "Cobot" in loop._soul

    def test_respond_success(self, mock_registry):
        """Should return LLM response."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        response = asyncio.run(loop._respond("Hi there"))

        assert response == "Hello human!"
        mock_registry.get_by_capability("llm").chat.assert_called_once()

    def test_respond_no_llm(self, mock_registry):
        """Should return error if no LLM configured."""
        mock_registry.get_by_capability = Mock(return_value=None)

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())
        response = asyncio.run(loop._respond("Hi"))

        assert "Error" in response
        assert "No LLM" in response

    def test_respond_llm_error(self, mock_registry):
        """Should return generic error message on LLM failure (CB-015)."""
        llm_plugin = mock_registry.get_by_capability("llm")
        llm_plugin.chat.side_effect = LLMError("API failed")

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())
        response = asyncio.run(loop._respond("Hi"))

        # CB-015: Generic error message returned, details logged internally
        assert "error" in response.lower()
        assert "Reference:" in response  # Should contain error reference


class TestCommunicationIntegration:
    """Test communication-based message handling via LoopPlugin."""

    def test_handle_message(self, mock_registry):
        """Should respond to incoming message via communication."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        msg = IncomingMessage(
            id="msg1",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello bot!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # Should have called LLM
        mock_registry.get_by_capability("llm").chat.assert_called_once()

        # Should have sent response via communication
        comm = mock_registry.get("communication")
        comm.send.assert_called_once()
        call_args = comm.send.call_args
        outgoing = call_args[0][0]
        assert isinstance(outgoing, OutgoingMessage)
        assert outgoing.channel_type == "telegram"
        assert outgoing.channel_id == "-100123"
        assert outgoing.content == "Hello human!"
        assert outgoing.reply_to == "msg1"

    def test_handle_message_calls_extension_points(self, mock_registry):
        """Should call extension chain at each step."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        msg = IncomingMessage(
            id="msg2",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # Check extension points were called
        called_points = [
            call[0][0] for call in loop.call_extension_chain.call_args_list
        ]
        assert "loop.on_message" in called_points
        assert "loop.transform_system_prompt" in called_points
        assert "loop.transform_history" in called_points
        assert "loop.before_llm" in called_points
        assert "loop.after_llm" in called_points
        assert "loop.transform_response" in called_points
        assert "loop.before_send" in called_points
        assert "loop.after_send" in called_points

    def test_handle_message_dedup(self, mock_registry):
        """Should not process same message twice."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        msg = IncomingMessage(
            id="msg1",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))
        asyncio.run(loop._handle_message(msg))

        # LLM should only be called once
        assert mock_registry.get_by_capability("llm").chat.call_count == 1

    def test_handle_message_abort_on_message(self, mock_registry):
        """Should abort if on_message extension sets abort."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def abort_on_message(point, ctx):
            if point == "loop.on_message":
                ctx["abort"] = True
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=abort_on_message)

        msg = IncomingMessage(
            id="msg_abort",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # LLM should NOT be called
        mock_registry.get_by_capability("llm").chat.assert_not_called()


class TestToolCalls:
    """Test tool call handling in LoopPlugin."""

    def test_respond_with_tool_call(self, mock_registry):
        """Should execute tool calls and continue."""
        llm_plugin = mock_registry.get_by_capability("llm")
        tools_plugin = mock_registry.get_by_capability("tools")

        # First call returns tool call, second returns final response
        llm_plugin.chat.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "test.txt"}',
                        },
                    }
                ],
                model="test",
            ),
            LLMResponse(content="File contents: hello", model="test"),
        ]

        tools_plugin.execute.return_value = "hello"
        tools_plugin.get_definitions.return_value = [
            {"type": "function", "function": {"name": "read_file"}}
        ]

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())
        response = asyncio.run(loop._respond("Read test.txt"))

        assert response == "File contents: hello"
        assert llm_plugin.chat.call_count == 2
        tools_plugin.execute.assert_called_once_with("read_file", {"path": "test.txt"})


class TestCobotConcurrency:
    """Test Cobot running multiple loop plugins concurrently."""

    def test_run_multiple_loops(self):
        """Should run all loop plugins via asyncio.gather."""
        registry = Mock(spec=PluginRegistry)
        registry.stop_all = AsyncMock()

        call_order = []

        loop1 = Mock()
        loop1.meta = Mock(id="loop1")
        loop1.run = AsyncMock(side_effect=lambda: call_order.append("loop1"))

        loop2 = Mock()
        loop2.meta = Mock(id="loop2")
        loop2.run = AsyncMock(side_effect=lambda: call_order.append("loop2"))

        registry.all_with_capability = Mock(return_value=[loop1, loop2])

        bot = Cobot(registry)
        asyncio.run(bot.run())

        # Both loops should have been called
        loop1.run.assert_called_once()
        loop2.run.assert_called_once()
        assert len(call_order) == 2

    def test_run_stops_registry_on_cancel(self):
        """Should stop all plugins when cancelled."""
        registry = Mock(spec=PluginRegistry)
        registry.stop_all = AsyncMock()

        async def hang_forever():
            await asyncio.sleep(999)

        loop1 = Mock()
        loop1.meta = Mock(id="loop1")
        loop1.run = AsyncMock(side_effect=hang_forever)
        registry.all_with_capability = Mock(return_value=[loop1])

        bot = Cobot(registry)

        async def run_with_timeout():
            task = asyncio.create_task(bot.run())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_with_timeout())
        registry.stop_all.assert_called_once()


class TestLoopRun:
    """Test the main poll loop in LoopPlugin."""

    def test_run_polls_and_handles(self, mock_registry):
        """Should poll for messages and handle them."""
        comm = mock_registry.get("communication")
        msg = IncomingMessage(
            id="poll1",
            channel_type="telegram",
            channel_id="-100",
            sender_id="1",
            sender_name="alice",
            content="Hi",
            timestamp=datetime.now(),
        )

        call_count = 0

        def poll_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [msg]
            return []

        comm.poll = Mock(side_effect=poll_once)

        loop = _make_loop(mock_registry)
        loop._interval = 0

        async def run_loop():
            await loop.start()
            task = asyncio.create_task(loop.run())
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_loop())

        # LLM should have been called for the message
        mock_registry.get_by_capability("llm").chat.assert_called_once()

    def test_run_recovers_from_poll_error(self, mock_registry):
        """Should catch poll exceptions and call on_error."""
        comm = mock_registry.get("communication")

        call_count = 0

        def poll_with_error():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Network down")
            return []

        comm.poll = Mock(side_effect=poll_with_error)

        loop = _make_loop(mock_registry)
        loop._interval = 0

        async def run_briefly():
            await loop.start()
            task = asyncio.create_task(loop.run())
            await asyncio.sleep(0.15)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(run_briefly())

        # Should have called on_error for the connection failure
        error_calls = [
            call
            for call in loop.call_extension_chain.call_args_list
            if call[0][0] == "loop.on_error"
        ]
        assert len(error_calls) >= 1

    def test_run_no_communication(self):
        """Should exit immediately if no communication plugin."""
        registry = Mock(spec=PluginRegistry)
        registry.get = Mock(return_value=None)

        loop = LoopPlugin()
        loop._registry = registry
        loop.call_extension_chain = AsyncMock(side_effect=lambda p, c: c)
        asyncio.run(loop.run())
        # Should not crash or hang


class TestLoopExtensionAborts:
    """Test abort semantics at each extension point in the pipeline."""

    def test_abort_before_llm(self, mock_registry):
        """Should return abort message if before_llm sets abort."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def abort_before_llm(point, ctx):
            if point == "loop.before_llm":
                ctx["abort"] = True
                ctx["abort_message"] = "Rate limited."
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=abort_before_llm)

        response = asyncio.run(loop._respond("Hi"))
        assert response == "Rate limited."
        mock_registry.get_by_capability("llm").chat.assert_not_called()

    def test_abort_before_send(self, mock_registry):
        """Should not send if before_send sets abort."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def abort_before_send(point, ctx):
            if point == "loop.before_send":
                ctx["abort"] = True
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=abort_before_send)

        msg = IncomingMessage(
            id="msg_nosend",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # LLM should be called, but send should NOT
        mock_registry.get_by_capability("llm").chat.assert_called_once()
        mock_registry.get("communication").send.assert_not_called()

    def test_abort_before_tool(self, mock_registry):
        """Should use abort message instead of executing tool."""
        llm_plugin = mock_registry.get_by_capability("llm")
        tools_plugin = mock_registry.get_by_capability("tools")

        llm_plugin.chat.side_effect = [
            LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "call1",
                        "function": {
                            "name": "dangerous_tool",
                            "arguments": "{}",
                        },
                    }
                ],
                model="test",
            ),
            LLMResponse(content="OK, tool was blocked.", model="test"),
        ]
        tools_plugin.get_definitions.return_value = [
            {"type": "function", "function": {"name": "dangerous_tool"}}
        ]

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def block_tool(point, ctx):
            if point == "loop.before_tool":
                ctx["abort"] = True
                ctx["abort_message"] = "Blocked by security."
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=block_tool)

        asyncio.run(loop._respond("Do dangerous thing"))

        # Tool should NOT be executed
        tools_plugin.execute.assert_not_called()
        # LLM gets called twice (tool call + follow-up with blocked result)
        assert llm_plugin.chat.call_count == 2


class TestLoopErrorHandling:
    """Test error recovery in the loop."""

    def test_send_failure_calls_on_error(self, mock_registry):
        """Should call loop.on_error when send returns False."""
        comm = mock_registry.get("communication")
        comm.send.return_value = False  # Send fails

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        msg = IncomingMessage(
            id="msg_sendfail",
            channel_type="telegram",
            channel_id="-100123",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # Should have called on_error extension
        error_calls = [
            call
            for call in loop.call_extension_chain.call_args_list
            if call[0][0] == "loop.on_error"
        ]
        assert len(error_calls) == 1
        assert error_calls[0][0][1]["hook"] == "send"

    def test_respond_empty_response(self, mock_registry):
        """Should return placeholder for empty LLM response."""
        llm_plugin = mock_registry.get_by_capability("llm")
        llm_plugin.chat.return_value = LLMResponse(content="", model="test")

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())
        response = asyncio.run(loop._respond("Hi"))

        assert response == "(No response generated)"


class TestLoopDedupTrimming:
    """Test dedup set management."""

    def test_dedup_trims_at_threshold(self, mock_registry):
        """Should trim processed events OrderedDict when it exceeds 1000 (CB-014)."""
        from collections import OrderedDict

        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        # Pre-fill with 1001 events (CB-014 uses OrderedDict instead of set)
        loop._processed_events = OrderedDict()
        for i in range(1001):
            loop._processed_events[f"telegram:-100:msg{i}"] = 1234567890.0

        assert len(loop._processed_events) == 1001

        # Process one more message — should trigger trim
        msg = IncomingMessage(
            id="msg_trim",
            channel_type="telegram",
            channel_id="-100",
            sender_id="456",
            sender_name="alice",
            content="Hello!",
            timestamp=datetime.now(),
        )

        asyncio.run(loop._handle_message(msg))

        # Should be trimmed (500 kept + 1 new = ~501)
        assert len(loop._processed_events) <= 502


class TestLoopTransformChains:
    """Test that extension chains can modify data flowing through the pipeline."""

    def test_transform_system_prompt(self, mock_registry):
        """Extension should be able to modify the system prompt."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def inject_context(point, ctx):
            if point == "loop.transform_system_prompt":
                ctx["prompt"] = ctx["prompt"] + "\nYou are in test mode."
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=inject_context)

        asyncio.run(loop._respond("Hi"))

        # Check the system message sent to LLM includes injected text
        llm = mock_registry.get_by_capability("llm")
        call_args = llm.chat.call_args
        messages = call_args[0][0]
        assert "You are in test mode." in messages[0]["content"]

    def test_transform_response(self, mock_registry):
        """Extension should be able to modify the response text."""
        loop = _make_loop(mock_registry)
        asyncio.run(loop.start())

        async def append_footer(point, ctx):
            if point == "loop.transform_response":
                ctx["text"] = ctx["text"] + " [modified]"
            return ctx

        loop.call_extension_chain = AsyncMock(side_effect=append_footer)

        response = asyncio.run(loop._respond("Hi"))
        assert response == "Hello human! [modified]"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
