"""Tests for session plugin."""

from datetime import datetime


from .. import create_plugin, SessionPlugin
from ...communication import IncomingMessage, OutgoingMessage


class TestSessionPlugin:
    """Test SessionPlugin class."""

    def test_create_plugin(self):
        plugin = create_plugin()
        assert isinstance(plugin, SessionPlugin)

    def test_plugin_meta(self):
        plugin = create_plugin()
        assert plugin.meta.id == "session"
        assert "communication" in plugin.meta.dependencies

    def test_implements_communication_extension_points(self):
        plugin = create_plugin()
        assert "communication.receive" in plugin.meta.implements
        assert "communication.send" in plugin.meta.implements
        assert "communication.typing" in plugin.meta.implements
        assert "communication.channels" in plugin.meta.implements

    def test_defines_session_extension_points(self):
        plugin = create_plugin()
        assert "session.receive" in plugin.meta.extension_points
        assert "session.send" in plugin.meta.extension_points
        assert "session.typing" in plugin.meta.extension_points

    def test_defines_observer_extension_points(self):
        plugin = create_plugin()
        assert "session.on_receive" in plugin.meta.extension_points
        assert "session.on_send" in plugin.meta.extension_points


class TestSessionPollAllChannels:
    """Test poll_all_channels() method."""

    def test_poll_returns_empty_without_registry(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.start()

        messages = plugin.poll_all_channels()
        assert messages == []

    def test_poll_aggregates_from_channels(self):
        plugin = create_plugin()

        # Mock channel
        class MockChannel:
            def poll(self):
                return [
                    IncomingMessage(
                        id="1",
                        channel_type="telegram",
                        channel_id="-100123",
                        sender_id="456",
                        sender_name="alice",
                        content="Hello",
                        timestamp=datetime.now(),
                    )
                ]

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.receive":
                    return [("telegram", MockChannel(), "poll")]
                return []

        plugin._registry = MockRegistry()
        plugin.configure({})
        plugin.start()

        messages = plugin.poll_all_channels()
        assert len(messages) == 1
        assert messages[0].content == "Hello"


class TestSessionSend:
    """Test send() method."""

    def test_send_without_registry_returns_false(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.start()

        result = plugin.send(
            OutgoingMessage(
                channel_type="telegram",
                channel_id="-100123",
                content="Test",
            )
        )
        assert result is False

    def test_send_routes_to_channel(self):
        plugin = create_plugin()

        sent_messages = []

        class MockChannel:
            def send(self, msg):
                sent_messages.append(msg)
                return True

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.send":
                    return [("telegram", MockChannel(), "send")]
                return []

        plugin._registry = MockRegistry()
        plugin.configure({})
        plugin.start()

        msg = OutgoingMessage(
            channel_type="telegram",
            channel_id="-100123",
            content="Test",
        )
        result = plugin.send(msg)

        assert result is True
        assert len(sent_messages) == 1
        assert sent_messages[0].content == "Test"


class TestSessionObservers:
    """Test session.on_receive and session.on_send observer extension points."""

    def test_on_receive_notifies_observers(self):
        plugin = create_plugin()

        observed = []

        class MockObserver:
            def on_receive(self, msg):
                observed.append(msg)

        class MockChannel:
            def poll(self):
                return [
                    IncomingMessage(
                        id="1",
                        channel_type="telegram",
                        channel_id="-100123",
                        sender_id="456",
                        sender_name="alice",
                        content="Hello",
                        timestamp=datetime.now(),
                    )
                ]

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.receive":
                    return [("telegram", MockChannel(), "poll")]
                if ext_point == "session.on_receive":
                    return [("lurker", MockObserver(), "on_receive")]
                return []

        plugin._registry = MockRegistry()
        messages = plugin.poll_all_channels()

        assert len(messages) == 1
        assert len(observed) == 1
        assert observed[0].content == "Hello"
        assert observed[0].channel_id == "-100123"

    def test_on_send_notifies_observers(self):
        plugin = create_plugin()

        observed = []

        class MockObserver:
            def on_send(self, msg):
                observed.append(msg)

        class MockChannel:
            def send(self, msg):
                return True

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.send":
                    return [("telegram", MockChannel(), "send")]
                if ext_point == "session.on_send":
                    return [("lurker", MockObserver(), "on_send")]
                return []

        plugin._registry = MockRegistry()

        msg = OutgoingMessage(
            channel_type="telegram",
            channel_id="-100123",
            content="Reply",
        )
        result = plugin.send(msg)

        assert result is True
        assert len(observed) == 1
        assert observed[0].content == "Reply"

    def test_on_send_not_called_on_failure(self):
        plugin = create_plugin()

        observed = []

        class MockObserver:
            def on_send(self, msg):
                observed.append(msg)

        class MockChannel:
            def send(self, msg):
                return False

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.send":
                    return [("telegram", MockChannel(), "send")]
                if ext_point == "session.on_send":
                    return [("lurker", MockObserver(), "on_send")]
                return []

        plugin._registry = MockRegistry()

        msg = OutgoingMessage(
            channel_type="telegram",
            channel_id="-100123",
            content="Reply",
        )
        result = plugin.send(msg)

        assert result is False
        assert len(observed) == 0

    def test_observer_error_does_not_break_flow(self):
        plugin = create_plugin()

        class MockObserver:
            def on_receive(self, msg):
                raise RuntimeError("observer broke")

        class MockChannel:
            def poll(self):
                return [
                    IncomingMessage(
                        id="1",
                        channel_type="telegram",
                        channel_id="-100123",
                        sender_id="456",
                        sender_name="alice",
                        content="Hello",
                        timestamp=datetime.now(),
                    )
                ]

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.receive":
                    return [("telegram", MockChannel(), "poll")]
                if ext_point == "session.on_receive":
                    return [("broken", MockObserver(), "on_receive")]
                return []

        plugin._registry = MockRegistry()

        # Should not raise — observer errors are caught
        messages = plugin.poll_all_channels()
        assert len(messages) == 1


class TestSessionGetChannels:
    """Test get_channels() method."""

    def test_get_channels_without_registry(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.start()

        channels = plugin.get_channels()
        assert channels == []

    def test_get_channels_from_implementations(self):
        plugin = create_plugin()

        class MockChannel:
            pass

        class MockRegistry:
            def get_implementations(self, ext_point):
                if ext_point == "session.receive":
                    return [
                        ("telegram", MockChannel(), "poll"),
                        ("discord", MockChannel(), "poll"),
                    ]
                return []

        plugin._registry = MockRegistry()
        plugin.configure({})
        plugin.start()

        channels = plugin.get_channels()
        assert "telegram" in channels
        assert "discord" in channels
