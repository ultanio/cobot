"""Tests for TelegramPlugin."""

import asyncio
import os
import tempfile
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from pathlib import Path

from ..plugin import (
    TelegramPlugin,
    TelegramMessage,
    GroupConfig,
    Message,
    CommunicationError,
    create_plugin,
)
from ...base import PluginMeta


# === Plugin Creation Tests ===


class TestPluginCreation:
    """Test plugin instantiation."""

    def test_create_plugin(self):
        """Test factory function."""
        plugin = create_plugin()
        assert isinstance(plugin, TelegramPlugin)

    def test_plugin_meta(self):
        """Test plugin metadata."""
        plugin = TelegramPlugin()
        assert plugin.meta.id == "telegram"
        assert plugin.meta.version == "0.2.0"
        assert "communication" in plugin.meta.capabilities
        assert "session" in plugin.meta.dependencies

    def test_plugin_implements_session(self):
        """Test plugin implements session extension points."""
        plugin = TelegramPlugin()
        assert "session.receive" in plugin.meta.implements
        assert "session.send" in plugin.meta.implements
        assert "session.typing" in plugin.meta.implements
        assert plugin.meta.implements["session.receive"] == "poll_updates"
        assert plugin.meta.implements["session.send"] == "send_message"
        assert plugin.meta.implements["session.typing"] == "send_typing"

    def test_plugin_extension_points(self):
        """Test plugin extension points."""
        plugin = TelegramPlugin()
        expected_points = [
            "telegram.on_message",
            "telegram.on_edit",
            "telegram.on_delete",
            "telegram.on_media",
        ]
        for point in expected_points:
            assert point in plugin.meta.extension_points

    def test_plugin_initial_state(self):
        """Test initial plugin state."""
        plugin = TelegramPlugin()
        assert plugin._bot_token is None
        assert plugin._groups == {}
        assert plugin._app is None
        assert plugin._bot is None
        assert plugin._running is False
        assert plugin._message_buffer == []


# === Configuration Tests ===


class TestPluginConfiguration:
    """Test plugin configuration."""

    def test_configure_with_token(self):
        """Test configuration with bot token."""
        plugin = TelegramPlugin()
        plugin.configure(
            {
                "bot_token": "123456:ABC-DEF",
                "groups": [{"id": -100123, "name": "test-group"}],
            }
        )
        assert plugin._bot_token == "123456:ABC-DEF"
        assert -100123 in plugin._groups
        assert plugin._groups[-100123].name == "test-group"

    def test_configure_from_env(self):
        """Test configuration from environment variable."""
        plugin = TelegramPlugin()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env_token_123"}):
            plugin.configure({})
        assert plugin._bot_token == "env_token_123"

    def test_configure_token_precedence(self):
        """Test that config token takes precedence over env."""
        plugin = TelegramPlugin()
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "env_token"}):
            plugin.configure({"bot_token": "config_token"})
        assert plugin._bot_token == "config_token"

    def test_configure_without_token(self, capsys):
        """Test configuration without bot token shows warning."""
        plugin = TelegramPlugin()
        with patch.dict(os.environ, {}, clear=True):
            # Remove TELEGRAM_BOT_TOKEN if it exists
            os.environ.pop("TELEGRAM_BOT_TOKEN", None)
            plugin.configure({})
        assert plugin._bot_token is None
        captured = capsys.readouterr()
        assert "No bot_token configured" in captured.err

    def test_configure_multiple_groups(self):
        """Test configuration with multiple groups."""
        plugin = TelegramPlugin()
        plugin.configure(
            {
                "bot_token": "test_token",
                "groups": [
                    {"id": -100123, "name": "group-1"},
                    {"id": -100456, "name": "group-2"},
                    {"id": -100789, "name": "group-3", "enabled": False},
                ],
            }
        )
        assert len(plugin._groups) == 3
        assert plugin._groups[-100123].enabled is True
        assert plugin._groups[-100456].enabled is True
        assert plugin._groups[-100789].enabled is False

    def test_configure_media_dir(self):
        """Test media directory configuration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            media_path = os.path.join(tmpdir, "media")
            plugin = TelegramPlugin()
            plugin.configure(
                {
                    "bot_token": "test",
                    "media_dir": media_path,
                }
            )
            assert plugin._media_dir == Path(media_path)
            assert plugin._media_dir.exists()

    def test_configure_default_media_dir(self):
        """Test default media directory."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        assert plugin._media_dir == Path("./media")

    def test_configure_group_without_name(self):
        """Test group config without name uses ID as name."""
        plugin = TelegramPlugin()
        plugin.configure(
            {
                "bot_token": "test",
                "groups": [{"id": -100999}],
            }
        )
        assert plugin._groups[-100999].name == "-100999"


# === GroupConfig Tests ===


class TestGroupConfig:
    """Test GroupConfig dataclass."""

    def test_create_group_config(self):
        """Test creating a GroupConfig."""
        config = GroupConfig(id=-100123, name="test")
        assert config.id == -100123
        assert config.name == "test"
        assert config.enabled is True

    def test_group_config_defaults(self):
        """Test GroupConfig default values."""
        config = GroupConfig(id=-100123)
        assert config.name == ""
        assert config.enabled is True

    def test_group_config_disabled(self):
        """Test disabled group."""
        config = GroupConfig(id=-100123, name="test", enabled=False)
        assert config.enabled is False


# === TelegramMessage Tests ===


class TestTelegramMessage:
    """Test TelegramMessage dataclass."""

    def test_create_message(self):
        """Test creating a TelegramMessage."""
        msg = TelegramMessage(
            group_id=-100123,
            group_name="test-group",
            message_id=42,
            from_user={"id": 1, "username": "alice"},
            timestamp="2026-02-13T11:00:00",
            text="Hello!",
        )
        assert msg.message_id == 42
        assert msg.text == "Hello!"
        assert msg.group_id == -100123
        assert msg.group_name == "test-group"

    def test_message_with_reply(self):
        """Test message with reply_to."""
        msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=42,
            from_user={"id": 1},
            timestamp="2026-02-13T11:00:00",
            text="Reply",
            reply_to=41,
        )
        assert msg.reply_to == 41

    def test_message_with_media(self):
        """Test message with media."""
        msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=42,
            from_user={"id": 1},
            timestamp="2026-02-13T11:00:00",
            text="",
            media={"type": "photo", "local_path": "/tmp/photo.jpg"},
        )
        assert msg.media["type"] == "photo"

    def test_message_to_dict(self):
        """Test converting message to dict."""
        msg = TelegramMessage(
            group_id=-100123,
            group_name="test-group",
            message_id=42,
            from_user={"id": 1, "username": "alice"},
            timestamp="2026-02-13T11:00:00",
            text="Hello!",
            reply_to=41,
            media={"type": "photo"},
        )
        d = msg.to_dict()

        assert d["group_id"] == -100123
        assert d["group_name"] == "test-group"
        assert d["message_id"] == 42
        assert d["from_user"]["username"] == "alice"
        assert d["text"] == "Hello!"
        assert d["reply_to"] == 41
        assert d["media"]["type"] == "photo"
        assert "timestamp" in d
        assert "raw" in d

    def test_message_defaults(self):
        """Test message default values."""
        msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=1,
            from_user={},
            timestamp="2026-01-01T00:00:00",
            text="",
        )
        assert msg.reply_to is None
        assert msg.edit_date is None
        assert msg.media is None
        assert msg.raw == {}


# === Extension Handlers Tests ===


class TestExtensionHandlers:
    """Test extension point handlers."""

    def test_register_handler(self):
        """Test registering a handler."""
        plugin = TelegramPlugin()

        def handler(ctx):
            pass

        plugin.register_handler("telegram.on_message", handler)
        assert handler in plugin._extension_handlers["telegram.on_message"]

    def test_register_multiple_handlers(self):
        """Test registering multiple handlers for same point."""
        plugin = TelegramPlugin()

        handlers = [lambda ctx: None for _ in range(3)]
        for h in handlers:
            plugin.register_handler("telegram.on_message", h)

        assert len(plugin._extension_handlers["telegram.on_message"]) == 3

    def test_register_handlers_different_points(self):
        """Test registering handlers for different extension points."""
        plugin = TelegramPlugin()

        plugin.register_handler("telegram.on_message", lambda ctx: None)
        plugin.register_handler("telegram.on_edit", lambda ctx: None)
        plugin.register_handler("telegram.on_media", lambda ctx: None)

        assert len(plugin._extension_handlers["telegram.on_message"]) == 1
        assert len(plugin._extension_handlers["telegram.on_edit"]) == 1
        assert len(plugin._extension_handlers["telegram.on_media"]) == 1

    def test_register_invalid_point(self):
        """Test registering handler for invalid extension point."""
        plugin = TelegramPlugin()
        plugin.register_handler("invalid.point", lambda ctx: None)
        # Should not raise, just ignore
        assert "invalid.point" not in plugin._extension_handlers

    def test_call_extension(self):
        """Test calling extension handlers."""
        plugin = TelegramPlugin()

        called = []

        def handler(ctx):
            called.append(ctx)

        plugin.register_handler("telegram.on_message", handler)
        plugin._call_extension("telegram.on_message", {"test": "data"})

        assert len(called) == 1
        assert called[0]["test"] == "data"

    def test_call_extension_multiple_handlers(self):
        """Test calling multiple handlers."""
        plugin = TelegramPlugin()

        results = []
        plugin.register_handler("telegram.on_message", lambda ctx: results.append(1))
        plugin.register_handler("telegram.on_message", lambda ctx: results.append(2))
        plugin.register_handler("telegram.on_message", lambda ctx: results.append(3))

        plugin._call_extension("telegram.on_message", {})

        assert results == [1, 2, 3]

    def test_call_extension_handler_error(self, capsys):
        """Test that handler errors don't crash the plugin."""
        plugin = TelegramPlugin()

        def bad_handler(ctx):
            raise ValueError("Test error")

        def good_handler(ctx):
            ctx["called"] = True

        plugin.register_handler("telegram.on_message", bad_handler)
        plugin.register_handler("telegram.on_message", good_handler)

        ctx = {}
        plugin._call_extension("telegram.on_message", ctx)

        # Good handler should still be called
        assert ctx.get("called") is True
        captured = capsys.readouterr()
        assert "Handler error" in captured.err

    def test_call_extension_with_registry(self):
        """Test calling extension with registry set."""
        plugin = TelegramPlugin()

        mock_registry = Mock()
        mock_registry.call_extension.return_value = {"registry": "called"}
        plugin.set_registry(mock_registry)

        result = plugin._call_extension("telegram.on_message", {"test": "data"})

        mock_registry.call_extension.assert_called_once_with(
            "telegram.on_message", {"test": "data"}
        )
        assert result["registry"] == "called"


# === Identity Tests ===


class TestIdentity:
    """Test get_identity method."""

    def test_identity_not_configured(self):
        """Test identity when not configured."""
        plugin = TelegramPlugin()
        identity = plugin.get_identity()
        assert identity["type"] == "telegram_bot"
        assert identity["status"] == "not_configured"

    def test_identity_configured(self):
        """Test identity when configured and started."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "123456:ABC-DEF"})
        asyncio.run(plugin.start())

        identity = plugin.get_identity()
        assert identity["type"] == "telegram_bot"
        assert "123456:ABC" in identity["token_prefix"]
        assert isinstance(identity["groups"], list)


# === Start/Stop Tests ===


class TestStartStop:
    """Test start and stop methods."""

    def test_start_without_token(self, capsys):
        """Test starting without token configured."""
        plugin = TelegramPlugin()
        asyncio.run(plugin.start())

        captured = capsys.readouterr()
        assert "Cannot start" in captured.err
        assert plugin._bot is None

    def test_start_with_token(self):
        """Test starting with token configured."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "123456:ABC-DEF"})
        asyncio.run(plugin.start())

        assert plugin._bot is not None
        assert plugin._app is not None
        assert plugin._running is True

    def test_stop(self, capsys):
        """Test stopping the plugin."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())
        asyncio.run(plugin.stop())

        assert plugin._running is False
        captured = capsys.readouterr()
        assert "stopped" in captured.err


# === Receive Messages Tests ===


class TestReceiveMessages:
    """Test receive method."""

    def test_receive_empty_buffer(self):
        """Test receiving with empty buffer."""
        plugin = TelegramPlugin()
        messages = plugin.receive(since_minutes=5)
        assert messages == []

    def test_receive_filters_old_messages(self):
        """Test that old messages are filtered out."""
        plugin = TelegramPlugin()

        # Add an old message
        old_msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=1,
            from_user={"id": 1, "username": "test"},
            timestamp="2020-01-01T00:00:00",  # Very old
            text="Old message",
        )
        plugin._message_buffer.append(old_msg)

        messages = plugin.receive(since_minutes=5)
        assert len(messages) == 0

    def test_receive_returns_recent_messages(self):
        """Test receiving recent messages."""
        plugin = TelegramPlugin()

        # Add a recent message
        recent_msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=1,
            from_user={"id": 1, "username": "alice"},
            timestamp=datetime.utcnow().isoformat(),
            text="Recent message",
        )
        plugin._message_buffer.append(recent_msg)

        messages = plugin.receive(since_minutes=5)
        assert len(messages) == 1
        assert messages[0].content == "Recent message"
        assert messages[0].sender == "alice"

    def test_receive_converts_to_message_format(self):
        """Test that TelegramMessage is converted to Message."""
        plugin = TelegramPlugin()

        tm = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=42,
            from_user={"id": 1, "username": "bob"},
            timestamp=datetime.utcnow().isoformat(),
            text="Test content",
        )
        plugin._message_buffer.append(tm)

        messages = plugin.receive(since_minutes=5)
        assert len(messages) == 1

        msg = messages[0]
        assert isinstance(msg, Message)
        assert msg.id == "42"
        assert msg.sender == "bob"
        assert msg.content == "Test content"


# === Send Messages Tests ===


class TestSendMessages:
    """Test send method (legacy API)."""

    def test_send_without_bot(self):
        """Test sending without initialized bot returns failed."""
        plugin = TelegramPlugin()
        result = plugin.send("-100123", "Hello")
        assert result == "failed"

    def test_send_invalid_recipient(self):
        """Test sending to invalid recipient returns failed."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        # Invalid recipient (not a number) should return failed
        result = plugin.send("not_a_number", "Hello")
        assert result == "failed"


# === PluginMeta Tests ===


class TestPluginMeta:
    """Test PluginMeta dataclass."""

    def test_create_meta(self):
        """Test creating PluginMeta."""
        meta = PluginMeta(
            id="test",
            version="1.0.0",
            capabilities=["communication"],
        )
        assert meta.id == "test"
        assert meta.version == "1.0.0"

    def test_meta_defaults(self):
        """Test PluginMeta default values."""
        meta = PluginMeta(id="test", version="1.0.0")
        assert meta.capabilities == []
        assert meta.dependencies == []
        assert meta.priority == 50
        assert meta.extension_points == []
        assert meta.implements == {}


# === Integration Tests ===


class TestIntegration:
    """Integration tests for the plugin."""

    def test_full_configuration_flow(self):
        """Test complete configuration flow."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.configure(
                {
                    "bot_token": "123456:ABC-DEF",
                    "groups": [
                        {"id": -100111, "name": "group-a"},
                        {"id": -100222, "name": "group-b"},
                    ],
                    "media_dir": os.path.join(tmpdir, "media"),
                }
            )

            asyncio.run(plugin.start())

            assert plugin._running
            assert len(plugin._groups) == 2
            assert plugin._media_dir.exists()

            identity = plugin.get_identity()
            assert len(identity["groups"]) == 2

            asyncio.run(plugin.stop())
            assert not plugin._running

    def test_handler_receives_message_context(self):
        """Test that handlers receive proper context."""
        plugin = TelegramPlugin()

        received_contexts = []

        def capture_handler(ctx):
            received_contexts.append(ctx.copy())

        plugin.register_handler("telegram.on_message", capture_handler)

        # Simulate calling extension
        test_msg = TelegramMessage(
            group_id=-100123,
            group_name="test",
            message_id=42,
            from_user={"id": 1, "username": "alice"},
            timestamp="2026-02-13T12:00:00",
            text="Hello!",
        )

        ctx = {"message": test_msg.to_dict()}
        plugin._call_extension("telegram.on_message", ctx)

        assert len(received_contexts) == 1
        assert received_contexts[0]["message"]["text"] == "Hello!"
        assert received_contexts[0]["message"]["from_user"]["username"] == "alice"


# === Session Extension Point Tests ===


class TestSessionReceive:
    """Test session.receive implementation (poll_updates)."""

    def test_poll_updates_without_bot(self):
        """Test poll_updates returns empty list when not configured."""
        plugin = TelegramPlugin()
        messages = plugin.poll_updates()
        assert messages == []

    def test_poll_updates_returns_incoming_messages(self):
        """Test poll_updates returns IncomingMessage objects."""
        from cobot.plugins.session import IncomingMessage

        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        # Mock httpx response
        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.get.return_value = MagicMock(
                json=Mock(
                    return_value={
                        "ok": True,
                        "result": [
                            {
                                "update_id": 1,
                                "message": {
                                    "message_id": 42,
                                    "chat": {"id": -100123, "title": "Test Group"},
                                    "from": {
                                        "id": 1,
                                        "username": "alice",
                                        "first_name": "Alice",
                                    },
                                    "date": 1707830400,  # 2024-02-13T12:00:00
                                    "text": "Hello!",
                                },
                            }
                        ],
                    }
                )
            )
            mock_client_class.return_value = mock_client

            messages = plugin.poll_updates()

        assert len(messages) == 1
        msg = messages[0]
        assert isinstance(msg, IncomingMessage)
        assert msg.id == "42"
        assert msg.channel_type == "telegram"
        assert msg.channel_id == "-100123"
        assert msg.sender_name == "Alice"
        assert msg.content == "Hello!"


class TestSessionSend:
    """Test session.send implementation (send_message)."""

    def test_send_message_without_token(self):
        """Test send_message returns False when not configured."""
        from cobot.plugins.session import OutgoingMessage

        plugin = TelegramPlugin()
        result = plugin.send_message(
            OutgoingMessage(
                channel_type="telegram",
                channel_id="-100123",
                content="Test",
            )
        )
        assert result is False

    def test_send_message_success(self):
        """Test send_message returns True on success."""
        from cobot.plugins.session import OutgoingMessage

        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.post.return_value = MagicMock(
                json=Mock(return_value={"ok": True, "result": {"message_id": 1}})
            )
            mock_client_class.return_value = mock_client

            result = plugin.send_message(
                OutgoingMessage(
                    channel_type="telegram",
                    channel_id="-100123",
                    content="Hello!",
                    reply_to="42",
                )
            )

        assert result is True
        # Verify the request
        call_args = mock_client.post.call_args
        assert "sendMessage" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["chat_id"] == -100123
        assert payload["text"] == "Hello!"
        assert payload["reply_to_message_id"] == 42


class TestSessionTyping:
    """Test session.typing implementation (send_typing)."""

    def test_send_typing_without_token(self):
        """Test send_typing does nothing when not configured."""
        plugin = TelegramPlugin()
        # Should not raise
        plugin.send_typing("-100123")

    def test_send_typing_calls_api(self):
        """Test send_typing calls Telegram API."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.post.return_value = MagicMock(
                json=Mock(return_value={"ok": True})
            )
            mock_client_class.return_value = mock_client

            plugin.send_typing("-100123")

        # Verify the request
        call_args = mock_client.post.call_args
        assert "sendChatAction" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["chat_id"] == -100123
        assert payload["action"] == "typing"


class TestDefaultChannel:
    """Test get_default_channel_id helper."""

    def test_default_channel_not_configured(self):
        """Test returns None when no groups configured."""
        plugin = TelegramPlugin()
        assert plugin.get_default_channel_id() is None

    def test_default_channel_from_config(self):
        """Test returns configured default_group."""
        plugin = TelegramPlugin()
        plugin.configure({
            "bot_token": "test",
            "groups": [{"id": -100111}, {"id": -100222}],
            "default_group": -100222,
        })
        assert plugin.get_default_channel_id() == "-100222"

    def test_default_channel_first_group(self):
        """Test returns first group when no default set."""
        plugin = TelegramPlugin()
        plugin.configure({
            "bot_token": "test",
            "groups": [{"id": -100111}, {"id": -100222}],
        })
        assert plugin.get_default_channel_id() == "-100111"


class TestLongPolling:
    """Test long polling configuration."""

    def test_default_poll_timeout(self):
        """Test default poll timeout is 30 seconds."""
        plugin = TelegramPlugin()
        assert plugin._poll_timeout == 30

    def test_custom_poll_timeout(self):
        """Test configurable poll timeout."""
        plugin = TelegramPlugin()
        plugin.configure({
            "bot_token": "test",
            "poll_timeout": 60,
        })
        assert plugin._poll_timeout == 60

    def test_poll_uses_configured_timeout(self):
        """Test poll_updates uses the configured timeout."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test", "poll_timeout": 45})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.get.return_value = MagicMock(
                json=Mock(return_value={"ok": True, "result": []})
            )
            mock_client_class.return_value = mock_client

            plugin.poll_updates()

        # Verify timeout in params
        call_args = mock_client.get.call_args
        params = call_args[1]["params"]
        assert params["timeout"] == 45

        # Verify httpx client timeout is longer than poll timeout
        client_timeout = mock_client_class.call_args[1]["timeout"]
        assert client_timeout == 50.0  # poll_timeout + 5


class TestOnBeforeLlmCall:
    """Test on_before_llm_call hook for typing indicator."""

    def test_on_before_llm_call_sends_typing_for_telegram(self):
        """Test hook sends typing indicator for telegram channel."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.__enter__ = Mock(return_value=mock_client)
            mock_client.__exit__ = Mock(return_value=False)
            mock_client.post.return_value = MagicMock(
                json=Mock(return_value={"ok": True})
            )
            mock_client_class.return_value = mock_client

            ctx = {
                "channel_type": "telegram",
                "channel_id": "-100123",
                "messages": [],
                "model": "test-model",
            }
            result = asyncio.run(plugin.on_before_llm_call(ctx))

        # Should return ctx unchanged
        assert result == ctx

        # Should have called typing API
        call_args = mock_client.post.call_args
        assert "sendChatAction" in call_args[0][0]

    def test_on_before_llm_call_ignores_other_channels(self):
        """Test hook ignores non-telegram channels."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            ctx = {
                "channel_type": "discord",
                "channel_id": "123",
                "messages": [],
            }
            result = asyncio.run(plugin.on_before_llm_call(ctx))

        # Should return ctx unchanged
        assert result == ctx

        # Should NOT have called any API
        mock_client.post.assert_not_called()

    def test_on_before_llm_call_handles_missing_channel(self):
        """Test hook handles missing channel info gracefully."""
        plugin = TelegramPlugin()
        plugin.configure({"bot_token": "test"})
        asyncio.run(plugin.start())

        with patch("httpx.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            ctx = {"messages": [], "model": "test-model"}
            result = asyncio.run(plugin.on_before_llm_call(ctx))

        # Should return ctx unchanged
        assert result == ctx

        # Should NOT have called any API
        mock_client.post.assert_not_called()
