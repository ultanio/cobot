"""Tests for persistence plugin - conversation history management."""

import pytest
from pathlib import Path
import tempfile
import json

from cobot.plugins.persistence.plugin import PersistencePlugin


class TestPersistencePlugin:
    """Tests for the persistence plugin."""

    @pytest.fixture
    def plugin(self):
        """Create a configured and enabled persistence plugin."""
        plugin = PersistencePlugin()
        plugin.configure({"persistence": {"enabled": True}})
        # Use temp directory for memory
        plugin._memory_dir = Path(tempfile.mkdtemp())
        plugin._enabled = True
        return plugin

    @pytest.fixture
    def disabled_plugin(self):
        """Create a disabled persistence plugin."""
        plugin = PersistencePlugin()
        plugin.configure({"persistence": {"enabled": False}})
        return plugin

    # --- Configuration Tests ---

    def test_disabled_by_default(self):
        """Test that persistence is disabled by default."""
        plugin = PersistencePlugin()
        plugin.configure({})
        assert plugin._enabled is False

    def test_enabled_via_config(self):
        """Test enabling via config."""
        plugin = PersistencePlugin()
        plugin.configure({"persistence": {"enabled": True}})
        assert plugin._enabled is True

    # --- Message Storage Tests ---

    @pytest.mark.asyncio
    async def test_on_message_received_stores_user_message(self, plugin):
        """Test that user messages are stored."""
        ctx = {
            "sender": "test_user",
            "message": "Hello, world!",
        }

        result = await plugin.on_message_received(ctx)

        # Should return ctx unchanged
        assert result == ctx

        # Should have stored the message
        conv = plugin._get_conversation("test_user")
        assert len(conv["messages"]) == 1
        assert conv["messages"][0]["role"] == "user"
        assert conv["messages"][0]["content"] == "Hello, world!"

    @pytest.mark.asyncio
    async def test_on_message_received_disabled(self, disabled_plugin):
        """Test that disabled plugin doesn't store messages."""
        ctx = {"sender": "test_user", "message": "Hello"}

        result = await disabled_plugin.on_message_received(ctx)

        assert result == ctx
        # No conversation should exist
        assert "test_user" not in disabled_plugin._conversations

    @pytest.mark.asyncio
    async def test_on_after_send_stores_assistant_message(self, plugin):
        """Test that assistant responses are stored."""
        # First, set current peer
        plugin._current_peer = "test_user"

        ctx = {
            "recipient": "test_user",
            "text": "Hello! How can I help?",
        }

        result = await plugin.on_after_send(ctx)

        assert result == ctx
        conv = plugin._get_conversation("test_user")
        assert len(conv["messages"]) == 1
        assert conv["messages"][0]["role"] == "assistant"
        assert conv["messages"][0]["content"] == "Hello! How can I help?"

    # --- History Injection Tests ---

    @pytest.mark.asyncio
    async def test_transform_history_injects_previous_messages(self, plugin):
        """Test that history is injected into messages."""
        # Pre-populate conversation history
        plugin._add_message("test_user", "user", "First message")
        plugin._add_message("test_user", "assistant", "First response")
        plugin._add_message("test_user", "user", "Second message")

        # Simulate incoming message context
        ctx = {
            "peer": "test_user",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Second message"},
            ],
        }

        result = await plugin.transform_history(ctx)

        # Should have: system + history + current user message
        messages = result["messages"]
        assert len(messages) == 4  # system + 2 history + current

        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "First message"
        assert messages[2]["role"] == "assistant"
        assert messages[2]["content"] == "First response"
        assert messages[3]["role"] == "user"
        assert messages[3]["content"] == "Second message"

    @pytest.mark.asyncio
    async def test_transform_history_empty_history(self, plugin):
        """Test transform_history with no previous messages."""
        ctx = {
            "peer": "new_user",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
        }

        result = await plugin.transform_history(ctx)

        # Should be unchanged
        assert len(result["messages"]) == 2

    @pytest.mark.asyncio
    async def test_transform_history_disabled(self, disabled_plugin):
        """Test that disabled plugin doesn't modify messages."""
        ctx = {
            "peer": "test_user",
            "messages": [{"role": "user", "content": "Hello"}],
        }

        result = await disabled_plugin.transform_history(ctx)

        assert result == ctx

    # --- Full Conversation Flow Tests ---

    @pytest.mark.asyncio
    async def test_conversation_flow(self, plugin):
        """Test a full conversation flow with multiple turns."""
        # Turn 1: User sends message
        await plugin.on_message_received(
            {
                "sender": "alice",
                "message": "What is 2+2?",
            }
        )

        # Turn 1: Assistant responds
        await plugin.on_after_send(
            {
                "recipient": "alice",
                "text": "2+2 equals 4.",
            }
        )

        # Turn 2: User sends another message
        await plugin.on_message_received(
            {
                "sender": "alice",
                "message": "And 3+3?",
            }
        )

        # Check conversation state
        conv = plugin._get_conversation("alice")
        assert len(conv["messages"]) == 3

        # Turn 2: Check history injection
        ctx = {
            "peer": "alice",
            "messages": [
                {"role": "system", "content": "You are a math tutor."},
                {"role": "user", "content": "And 3+3?"},
            ],
        }

        result = await plugin.transform_history(ctx)
        messages = result["messages"]

        # Should have system + (user, assistant) history + current user
        assert len(messages) == 4
        assert messages[0]["content"] == "You are a math tutor."
        assert messages[1]["content"] == "What is 2+2?"
        assert messages[2]["content"] == "2+2 equals 4."
        assert messages[3]["content"] == "And 3+3?"

    @pytest.mark.asyncio
    async def test_separate_conversations_per_peer(self, plugin):
        """Test that different peers have separate conversations."""
        # Alice's conversation
        await plugin.on_message_received({"sender": "alice", "message": "Hi Alice"})
        await plugin.on_after_send({"recipient": "alice", "text": "Hello Alice!"})

        # Bob's conversation
        await plugin.on_message_received({"sender": "bob", "message": "Hi Bob"})
        await plugin.on_after_send({"recipient": "bob", "text": "Hello Bob!"})

        # Check they're separate
        alice_conv = plugin._get_conversation("alice")
        bob_conv = plugin._get_conversation("bob")

        assert len(alice_conv["messages"]) == 2
        assert len(bob_conv["messages"]) == 2
        assert alice_conv["messages"][0]["content"] == "Hi Alice"
        assert bob_conv["messages"][0]["content"] == "Hi Bob"

    # --- Persistence Tests ---

    def test_conversation_persists_to_file(self, plugin):
        """Test that conversations are saved to disk."""
        plugin._add_message("test_user", "user", "Persistent message")

        # Check file was created
        path = plugin._get_path("test_user")
        assert path.exists()

        # Check content
        data = json.loads(path.read_text())
        assert len(data["messages"]) == 1
        assert data["messages"][0]["content"] == "Persistent message"

    def test_conversation_loads_from_file(self, plugin):
        """Test that conversations are loaded from disk."""
        # Write directly to file
        path = plugin._get_path("loaded_user")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "messages": [
                        {"role": "user", "content": "Old message", "timestamp": 123}
                    ]
                }
            )
        )

        # Load via plugin
        conv = plugin._get_conversation("loaded_user")
        assert len(conv["messages"]) == 1
        assert conv["messages"][0]["content"] == "Old message"


class TestStdinModePersistence:
    """Tests specific to stdin mode persistence behavior."""

    @pytest.fixture
    def plugin(self):
        """Create plugin configured for stdin mode."""
        plugin = PersistencePlugin()
        plugin.configure({"persistence": {"enabled": True}})
        plugin._memory_dir = Path(tempfile.mkdtemp())
        plugin._enabled = True
        return plugin

    @pytest.mark.asyncio
    async def test_stdin_peer_conversation(self, plugin):
        """Test that stdin messages are tracked under 'stdin' peer."""
        # Simulate stdin mode messages
        await plugin.on_message_received(
            {
                "sender": "stdin",
                "message": "Remember this: 42",
            }
        )

        await plugin.on_after_send(
            {
                "recipient": "stdin",
                "text": "I'll remember that the number is 42.",
            }
        )

        await plugin.on_message_received(
            {
                "sender": "stdin",
                "message": "What number?",
            }
        )

        # Check history injection
        ctx = {
            "peer": "stdin",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What number?"},
            ],
        }

        result = await plugin.transform_history(ctx)
        messages = result["messages"]

        # Should have full history
        assert len(messages) == 4
        assert "Remember this: 42" in messages[1]["content"]
        assert "42" in messages[2]["content"]
        assert messages[3]["content"] == "What number?"

    @pytest.mark.asyncio
    async def test_remember_numbers_scenario(self, plugin):
        """Test the 'remember these numbers' scenario from stdin mode.

        This tests the exact flow that was broken: user tells agent to
        remember a series of numbers, then asks what they were.
        """
        # User: I'll tell you some numbers
        await plugin.on_message_received(
            {
                "sender": "stdin",
                "message": "I'll tell you some numbers. Please remember them.",
            }
        )
        await plugin.on_after_send(
            {
                "recipient": "stdin",
                "text": "Sure, go ahead! I'll remember the numbers you share.",
            }
        )

        # User tells numbers one by one
        numbers = ["1", "2", "3", "7", "8", "9"]
        for num in numbers:
            await plugin.on_message_received(
                {
                    "sender": "stdin",
                    "message": num,
                }
            )
            await plugin.on_after_send(
                {
                    "recipient": "stdin",
                    "text": f"Got it, noted {num}. What's next?",
                }
            )

        # User asks what the numbers were
        await plugin.on_message_received(
            {
                "sender": "stdin",
                "message": "What are the numbers?",
            }
        )

        # Verify history contains all numbers
        conv = plugin._get_conversation("stdin")
        messages = conv.get("messages", [])

        # Should have: intro + response + (6 numbers * 2) + final question = 15 messages
        assert len(messages) == 15

        # Extract all user messages
        user_messages = [m["content"] for m in messages if m["role"] == "user"]

        # All numbers should be in the conversation
        for num in numbers:
            assert num in user_messages

        # Check history injection for final question
        ctx = {
            "peer": "stdin",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "What are the numbers?"},
            ],
        }

        result = await plugin.transform_history(ctx)
        injected = result["messages"]

        # Should inject all previous messages (excluding last user msg which is current)
        # system + 14 history messages + current = 16 total
        assert len(injected) == 16

        # The history should contain all the numbers
        history_content = " ".join(m["content"] for m in injected)
        for num in numbers:
            assert num in history_content, f"Number {num} not found in history"
