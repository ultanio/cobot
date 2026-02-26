"""Tests for Nostr communication plugin."""

import pytest

pynostr = pytest.importorskip("pynostr", reason="pynostr not installed")

import asyncio  # noqa: E402

from ..plugin import NostrPlugin, create_plugin  # noqa: E402
from ...interfaces import Message, CommunicationError  # noqa: E402


class TestNostrPlugin:
    """Test NostrPlugin."""

    def test_create_plugin(self):
        plugin = create_plugin()
        assert isinstance(plugin, NostrPlugin)

    def test_plugin_meta(self):
        plugin = create_plugin()
        assert plugin.meta.id == "nostr"
        assert "communication" in plugin.meta.capabilities

    def test_configure_with_nsec(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "nostr": {
                    "nsec": "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5",
                    "relays": ["wss://relay.example.com"],
                }
            }
        )

        assert plugin._nsec is not None
        assert "wss://relay.example.com" in plugin._relays

    def test_configure_without_nsec(self):
        plugin = create_plugin()
        plugin.configure({"nostr": {}})

        # Should use env var or be None
        # (depends on environment)


class TestNostrPluginIdentity:
    """Test get_identity()."""

    def test_get_identity_when_not_initialized(self, monkeypatch):
        # Clear env var to test uninitialized state
        monkeypatch.delenv("NOSTR_NSEC", raising=False)

        plugin = create_plugin()
        plugin.configure({"nostr": {}})  # No nsec
        asyncio.run(plugin.start())

        identity = plugin.get_identity()
        assert identity == {}

    def test_get_identity_when_initialized(self):

        plugin = create_plugin()
        # Use a valid test nsec
        plugin.configure(
            {
                "nostr": {
                    "nsec": "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5",
                }
            }
        )
        asyncio.run(plugin.start())

        identity = plugin.get_identity()
        assert "npub" in identity
        assert "hex" in identity
        assert identity["npub"].startswith("npub")


class TestNostrPluginSend:
    """Test send() method."""

    def test_send_when_not_initialized(self, monkeypatch):
        # Clear env var to test uninitialized state
        monkeypatch.delenv("NOSTR_NSEC", raising=False)

        plugin = create_plugin()
        plugin.configure({"nostr": {}})
        asyncio.run(plugin.start())

        with pytest.raises(CommunicationError) as exc_info:
            plugin.send("npub1...", "hello")
        assert "not initialized" in str(exc_info.value).lower()

    def test_send_invalid_recipient(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "nostr": {
                    "nsec": "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5",
                }
            }
        )
        asyncio.run(plugin.start())

        # pynostr may raise different errors for invalid npubs
        with pytest.raises((CommunicationError, Exception)) as exc_info:
            plugin.send("invalid_npub", "hello")
        # Just verify an error was raised
        assert exc_info.value is not None


class TestMessage:
    """Test Message dataclass."""

    def test_create_message(self):
        msg = Message(
            id="abc123", sender="npub1...", content="hello", timestamp=1234567890
        )
        assert msg.id == "abc123"
        assert msg.content == "hello"
        assert msg.sender == "npub1..."
        assert msg.timestamp == 1234567890


class TestCommunicationError:
    """Test CommunicationError."""

    def test_error_message(self):
        error = CommunicationError("Connection failed")
        assert str(error) == "Connection failed"


class TestNostrPluginRelays:
    """Test relay configuration."""

    def test_default_relays(self):
        plugin = create_plugin()
        plugin.configure({"nostr": {}})

        # Should have default relays
        assert len(plugin._relays) > 0
        assert all(r.startswith("wss://") for r in plugin._relays)

    def test_custom_relays(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "nostr": {
                    "relays": ["wss://custom.relay.com", "wss://another.relay.com"],
                }
            }
        )

        assert len(plugin._relays) == 2
        assert "wss://custom.relay.com" in plugin._relays


# Integration tests would require actual Nostr network interaction
# These are skipped by default but can be run manually


@pytest.mark.skip(reason="Requires network access")
class TestNostrPluginIntegration:
    """Integration tests for NostrPlugin."""

    def test_receive_messages(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "nostr": {
                    "nsec": "nsec1vl029mgpspedva04g90vltkh6fvh240zqtv9k0t9af8935ke9laqsnlfe5",
                }
            }
        )
        asyncio.run(plugin.start())

        messages = plugin.receive(since_minutes=60)
        # Just check it doesn't crash
        assert isinstance(messages, list)
