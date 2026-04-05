"""Tests for lurker plugin."""

import json
import pytest
from datetime import datetime, timezone

from cobot.plugins.lurker.plugin import LurkerPlugin
from cobot.plugins.communication import IncomingMessage, OutgoingMessage


@pytest.fixture
def lurker(tmp_path):
    """Create a configured lurker plugin."""
    plugin = LurkerPlugin()
    plugin.configure({
        "lurker": {
            "channels": [
                {"id": "-100111", "name": "dev-chat"},
                {"id": "-100222", "name": "announcements"},
            ],
            "sink": "jsonl",
            "base_dir": str(tmp_path / "lurker"),
        }
    })
    return plugin


@pytest.fixture
def lurker_md(tmp_path):
    """Lurker with markdown sink."""
    plugin = LurkerPlugin()
    plugin.configure({
        "lurker": {
            "channels": [{"id": "-100111", "name": "dev-chat"}],
            "sink": "markdown",
            "base_dir": str(tmp_path / "lurker"),
        }
    })
    return plugin


@pytest.fixture
def lurker_nosink(tmp_path):
    """Lurker with no sink (extension points only)."""
    plugin = LurkerPlugin()
    plugin.configure({
        "lurker": {
            "channels": [{"id": "-100111", "name": "dev-chat"}],
            "sink": "none",
            "base_dir": str(tmp_path / "lurker"),
        }
    })
    return plugin


def make_incoming(channel_id="-100111", content="hello world", sender_name="alice",
                  sender_id="42", channel_type="telegram", msg_id="msg_1",
                  metadata=None) -> IncomingMessage:
    """Build an IncomingMessage."""
    return IncomingMessage(
        id=msg_id,
        channel_type=channel_type,
        channel_id=channel_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        timestamp=datetime(2026, 2, 18, 6, 0, 0, tzinfo=timezone.utc),
        metadata=metadata or {},
    )


def make_outgoing(channel_id="-100111", content="bot reply",
                  channel_type="telegram", reply_to="msg_1") -> OutgoingMessage:
    """Build an OutgoingMessage."""
    return OutgoingMessage(
        channel_type=channel_type,
        channel_id=channel_id,
        content=content,
        reply_to=reply_to,
    )


class TestLurkerConfig:
    def test_channels_parsed(self, lurker):
        assert lurker.is_lurked("-100111")
        assert lurker.is_lurked("-100222")
        assert not lurker.is_lurked("-100999")

    def test_channel_names(self, lurker):
        assert lurker._channel_name("-100111") == "dev-chat"
        assert lurker._channel_name("-100999") == "-100999"

    def test_channel_name_from_metadata(self, lurker):
        """Channel plugins can provide group_name in metadata."""
        name = lurker._channel_name("-100111", {"group_name": "From Telegram"})
        assert name == "From Telegram"

    def test_empty_config(self):
        plugin = LurkerPlugin()
        plugin.configure({})
        assert not plugin.is_lurked("anything")

    def test_sink_default(self):
        plugin = LurkerPlugin()
        plugin.configure({"lurker": {"channels": [{"id": "1"}]}})
        assert plugin._sink == "jsonl"


class TestIncomingMessages:
    def test_lurked_channel_is_observed(self, lurker):
        lurker.observe_incoming(make_incoming(channel_id="-100111"))
        assert lurker._counts["-100111"] == 1

    def test_non_lurked_channel_ignored(self, lurker):
        lurker.observe_incoming(make_incoming(channel_id="-100999"))
        assert "-100999" not in lurker._counts

    def test_counts_multiple(self, lurker):
        for _ in range(3):
            lurker.observe_incoming(make_incoming(channel_id="-100111"))
        assert lurker._counts["-100111"] == 3


class TestOutgoingMessages:
    def test_lurked_channel_is_observed(self, lurker, tmp_path):
        lurker.observe_outgoing(make_outgoing(channel_id="-100111"))

        jsonl_files = list((tmp_path / "lurker").rglob("*.jsonl"))
        assert len(jsonl_files) == 1

        record = json.loads(jsonl_files[0].read_text().strip())
        assert record["direction"] == "outgoing"
        assert record["sender"] == "bot"
        assert record["text"] == "bot reply"

    def test_non_lurked_channel_ignored(self, lurker, tmp_path):
        lurker.observe_outgoing(make_outgoing(channel_id="-100999"))

        lurker_dir = tmp_path / "lurker"
        if lurker_dir.exists():
            assert list(lurker_dir.rglob("*.jsonl")) == []

    def test_counts_outgoing(self, lurker):
        lurker.observe_outgoing(make_outgoing(channel_id="-100111"))
        assert lurker._counts["-100111"] == 1


class TestBothDirections:
    def test_interleaved_log(self, lurker, tmp_path):
        lurker.observe_incoming(make_incoming(content="hi bot"))
        lurker.observe_outgoing(make_outgoing(content="hello human"))
        lurker.observe_incoming(make_incoming(content="thanks"))

        jsonl_files = list((tmp_path / "lurker").rglob("*.jsonl"))
        lines = jsonl_files[0].read_text().strip().split("\n")
        assert len(lines) == 3

        records = [json.loads(l) for l in lines]
        assert records[0]["direction"] == "incoming"
        assert records[0]["text"] == "hi bot"
        assert records[1]["direction"] == "outgoing"
        assert records[1]["text"] == "hello human"
        assert records[2]["direction"] == "incoming"
        assert records[2]["text"] == "thanks"

    def test_total_count(self, lurker):
        lurker.observe_incoming(make_incoming())
        lurker.observe_outgoing(make_outgoing())
        lurker.observe_incoming(make_incoming())
        assert lurker._counts["-100111"] == 3


class TestJsonlSink:
    def test_writes_complete_record(self, lurker, tmp_path):
        lurker.observe_incoming(make_incoming(content="test msg"))

        jsonl_files = list((tmp_path / "lurker").rglob("*.jsonl"))
        assert len(jsonl_files) == 1

        record = json.loads(jsonl_files[0].read_text().strip())
        assert record["text"] == "test msg"
        assert record["sender"] == "alice"
        assert record["sender_id"] == "42"
        assert record["channel"] == "-100111"
        assert record["channel_name"] == "dev-chat"
        assert record["direction"] == "incoming"
        assert record["event_id"] == "msg_1"
        assert "ts" in record

    def test_separate_files_per_channel(self, lurker, tmp_path):
        lurker.observe_incoming(make_incoming(channel_id="-100111"))
        lurker.observe_incoming(make_incoming(channel_id="-100222"))

        jsonl_files = list((tmp_path / "lurker").rglob("*.jsonl"))
        assert len(jsonl_files) == 2
        names = {f.stem for f in jsonl_files}
        assert "-100111" in names
        assert "-100222" in names


class TestMarkdownSink:
    def test_writes_markdown(self, lurker_md, tmp_path):
        lurker_md.observe_incoming(make_incoming(content="hello"))

        md_files = list((tmp_path / "lurker").rglob("*.md"))
        assert len(md_files) == 1

        content = md_files[0].read_text()
        assert "# dev-chat" in content
        assert "**alice**" in content
        assert "hello" in content

    def test_outgoing_has_arrow_prefix(self, lurker_md, tmp_path):
        lurker_md.observe_outgoing(make_outgoing(content="reply"))

        md_files = list((tmp_path / "lurker").rglob("*.md"))
        content = md_files[0].read_text()
        assert "→**bot**" in content


class TestNoSink:
    def test_no_files_written(self, lurker_nosink, tmp_path):
        lurker_nosink.observe_incoming(make_incoming())

        lurker_dir = tmp_path / "lurker"
        if lurker_dir.exists():
            assert list(lurker_dir.rglob("*.*")) == []

    def test_still_counts(self, lurker_nosink):
        lurker_nosink.observe_incoming(make_incoming())
        assert lurker_nosink._counts["-100111"] == 1


class TestWizard:
    def test_wizard_section(self):
        plugin = LurkerPlugin()
        section = plugin.wizard_section()
        assert section is not None
        assert section["key"] == "lurker"
