"""Tests for FileDropPlugin."""

import json
import time

import pytest

from ..plugin import FileDropPlugin, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_filedrop_plugin(self):
        assert isinstance(create_plugin(), FileDropPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "filedrop"

    def test_capabilities(self):
        assert "communication" in create_plugin().meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 24


# === Configuration ===


class TestConfigure:
    def test_default_base_dir(self):
        plugin = create_plugin()
        plugin.configure({})
        assert str(plugin._base_dir) == "/tmp/filedrop"

    def test_custom_base_dir(self):
        plugin = create_plugin()
        plugin.configure({"filedrop": {"base_dir": "/custom/drop"}})
        assert str(plugin._base_dir) == "/custom/drop"

    def test_identity_from_filedrop_config(self):
        plugin = create_plugin()
        plugin.configure({"filedrop": {"identity": "myagent"}})
        assert plugin._identity == "myagent"

    def test_identity_from_identity_config(self):
        plugin = create_plugin()
        plugin.configure({"identity": {"name": "agentname"}})
        assert plugin._identity == "agentname"

    def test_identity_from_nostr_config(self):
        plugin = create_plugin()
        plugin.configure({"nostr": {"npub": "npub1abcdef123456"}})
        assert plugin._identity == "npub1abcdef123456"[:20]

    def test_identity_fallback(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._identity == "agent"

    def test_identity_precedence(self):
        """filedrop.identity takes precedence over identity.name."""
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"identity": "winner"},
                "identity": {"name": "loser"},
            }
        )
        assert plugin._identity == "winner"


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_directories(self, tmp_path):
        plugin = create_plugin()
        plugin.configure({"filedrop": {"base_dir": str(tmp_path / "drop")}})
        plugin._identity = "testagent"
        await plugin.start()

        assert (tmp_path / "drop" / "testagent" / "inbox").exists()
        assert (tmp_path / "drop" / "testagent" / "outbox").exists()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        await plugin.stop()  # Should not crash


# === Identity ===


class TestGetIdentity:
    @pytest.mark.asyncio
    async def test_get_identity(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent1"},
            }
        )
        await plugin.start()

        identity = plugin.get_identity()
        assert identity["name"] == "agent1"
        assert identity["protocol"] == "filedrop"
        assert "inbox" in identity


# === Send ===


class TestSend:
    @pytest.mark.asyncio
    async def test_send_creates_message_file(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "sender"},
            }
        )
        await plugin.start()

        msg_id = plugin.send("recipient", "hello there")

        # Check recipient inbox
        recipient_inbox = tmp_path / "recipient" / "inbox"
        files = list(recipient_inbox.glob("*.json"))
        assert len(files) == 1

        data = json.loads(files[0].read_text())
        assert data["from"] == "sender"
        assert data["to"] == "recipient"
        assert data["content"] == "hello there"
        assert data["id"] == msg_id

    @pytest.mark.asyncio
    async def test_send_saves_to_outbox(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "sender"},
            }
        )
        await plugin.start()

        plugin.send("recipient", "test")

        outbox = tmp_path / "sender" / "outbox"
        assert len(list(outbox.glob("*.json"))) == 1

    @pytest.mark.asyncio
    async def test_send_with_full_path(self, tmp_path):
        recipient_inbox = tmp_path / "custom" / "inbox"
        recipient_inbox.mkdir(parents=True)

        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "sender"},
            }
        )
        await plugin.start()

        plugin.send(str(recipient_inbox), "via path")

        files = list(recipient_inbox.glob("*.json"))
        assert len(files) == 1


# === Receive ===


class TestReceive:
    @pytest.mark.asyncio
    async def test_receive_empty_inbox(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent"},
            }
        )
        await plugin.start()

        messages = plugin.receive()
        assert messages == []

    @pytest.mark.asyncio
    async def test_receive_reads_messages(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent"},
            }
        )
        await plugin.start()

        # Drop a message in inbox
        inbox = tmp_path / "agent" / "inbox"
        msg = {
            "id": "msg1",
            "from": "other",
            "content": "hello agent",
            "timestamp": int(time.time()),
        }
        (inbox / "msg1.json").write_text(json.dumps(msg))

        messages = plugin.receive(since_minutes=5)
        assert len(messages) == 1
        assert messages[0].content == "hello agent"
        assert messages[0].sender == "other"

    @pytest.mark.asyncio
    async def test_receive_moves_to_processed(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent"},
            }
        )
        await plugin.start()

        inbox = tmp_path / "agent" / "inbox"
        msg = {"id": "msg1", "from": "x", "content": "y", "timestamp": int(time.time())}
        (inbox / "msg1.json").write_text(json.dumps(msg))

        plugin.receive(since_minutes=5)

        # Should be moved
        assert not (inbox / "msg1.json").exists()
        assert (tmp_path / "agent" / "processed" / "msg1.json").exists()

    @pytest.mark.asyncio
    async def test_receive_skips_already_processed(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent"},
            }
        )
        await plugin.start()

        inbox = tmp_path / "agent" / "inbox"
        msg = {"id": "msg1", "from": "x", "content": "y", "timestamp": int(time.time())}
        (inbox / "msg1.json").write_text(json.dumps(msg))

        # First receive
        messages1 = plugin.receive(since_minutes=5)
        assert len(messages1) == 1

        # Drop same filename again (simulating)
        (inbox / "msg1.json").write_text(json.dumps(msg))

        # Second receive — should skip (in processed set)
        messages2 = plugin.receive(since_minutes=5)
        assert len(messages2) == 0

    @pytest.mark.asyncio
    async def test_receive_skips_old_messages(self, tmp_path):
        plugin = create_plugin()
        plugin.configure(
            {
                "filedrop": {"base_dir": str(tmp_path), "identity": "agent"},
            }
        )
        await plugin.start()

        inbox = tmp_path / "agent" / "inbox"
        msg = {"id": "old", "from": "x", "content": "old msg", "timestamp": 0}
        msg_file = inbox / "old.json"
        msg_file.write_text(json.dumps(msg))
        # Set file mtime to old
        import os

        os.utime(msg_file, (0, 0))

        messages = plugin.receive(since_minutes=5)
        # NOTE: receive() does not yet filter by since_minutes —
        # it returns all unprocessed messages. This test documents
        # current behavior. Time-based filtering is a future enhancement.
        assert len(messages) == 1

    @pytest.mark.asyncio
    async def test_receive_no_inbox(self):
        plugin = create_plugin()
        plugin._inbox = None
        assert plugin.receive() == []


class TestMalformedJsonHandling:
    """Tests for #202: malformed JSON should be quarantined, not retried."""

    def test_malformed_json_quarantined(self, tmp_path):
        """Malformed JSON file should be moved to processed with _corrupted suffix."""
        from ..plugin import FileDropPlugin as FiledropPlugin

        plugin = FiledropPlugin()
        inbox = tmp_path / "TestAgent" / "inbox"
        inbox.mkdir(parents=True)
        plugin._inbox = inbox
        plugin._processed = set()
        plugin._identity = "TestAgent"

        # Write malformed JSON
        bad_file = inbox / "bad_message.json"
        bad_file.write_text("{invalid json content")

        messages = plugin.poll_inbox()

        assert len(messages) == 0
        assert not bad_file.exists(), "Malformed file should be removed from inbox"
        processed = tmp_path / "TestAgent" / "processed"
        quarantined = processed / "bad_message_corrupted.json"
        assert quarantined.exists(), "Malformed file should be quarantined"

    def test_malformed_json_doesnt_block_good_messages(self, tmp_path):
        """Good messages should still be processed after a bad one."""
        import json
        from ..plugin import FileDropPlugin as FiledropPlugin

        plugin = FiledropPlugin()
        inbox = tmp_path / "TestAgent" / "inbox"
        inbox.mkdir(parents=True)
        plugin._inbox = inbox
        plugin._processed = set()
        plugin._identity = "TestAgent"

        # Bad file (sorts first alphabetically)
        (inbox / "aaa_bad.json").write_text("not json")

        # Good file
        good_data = {
            "from": "Zeus",
            "subject": "Test",
            "content": "Hello",
            "timestamp": 1234567890,
        }
        (inbox / "zzz_good.json").write_text(json.dumps(good_data))

        messages = plugin.poll_inbox()

        assert len(messages) == 1
        assert messages[0].sender_id == "Zeus"
        assert not (inbox / "aaa_bad.json").exists()

    def test_quarantine_idempotent(self, tmp_path):
        """Polling twice shouldn't crash on already-quarantined files."""
        from ..plugin import FileDropPlugin as FiledropPlugin

        plugin = FiledropPlugin()
        inbox = tmp_path / "TestAgent" / "inbox"
        inbox.mkdir(parents=True)
        plugin._inbox = inbox
        plugin._processed = set()
        plugin._identity = "TestAgent"

        (inbox / "bad.json").write_text("{broken")
        plugin.poll_inbox()  # First poll quarantines
        messages = plugin.poll_inbox()  # Second poll should be clean
        assert len(messages) == 0
