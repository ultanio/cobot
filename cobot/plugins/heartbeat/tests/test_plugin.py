"""Tests for HeartbeatPlugin."""

import pytest
from unittest.mock import Mock

from ..plugin import HeartbeatPlugin, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_heartbeat_plugin(self):
        assert isinstance(create_plugin(), HeartbeatPlugin)

    def test_new_instance(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "heartbeat"

    def test_dependencies(self):
        assert "cron" in create_plugin().meta.dependencies

    def test_priority(self):
        assert create_plugin().meta.priority == 45


# === Configuration ===


class TestConfigure:
    def test_default_disabled(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._enabled is False

    def test_enable(self):
        plugin = create_plugin()
        plugin.configure({"heartbeat": {"enabled": True}})
        assert plugin._enabled is True

    def test_custom_interval(self):
        plugin = create_plugin()
        plugin.configure({"heartbeat": {"interval_minutes": 30}})
        assert plugin._interval_minutes == 30

    def test_default_interval(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin._interval_minutes == 15

    def test_custom_prompt_file(self):
        plugin = create_plugin()
        plugin.configure({"heartbeat": {"prompt_file": "CUSTOM.md"}})
        assert plugin._prompt_file == "CUSTOM.md"

    def test_quiet_hours(self):
        plugin = create_plugin()
        plugin.configure({"heartbeat": {"quiet_hours": "23:00-07:00"}})
        assert plugin._quiet_hours == "23:00-07:00"


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_disabled(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.start()
        # Should not crash, just log "Disabled"

    @pytest.mark.asyncio
    async def test_start_enabled_no_cron(self):
        plugin = create_plugin()
        plugin.configure({"heartbeat": {"enabled": True}})
        plugin._registry = Mock()
        plugin._registry.get.return_value = None
        await plugin.start()
        # Should log error about missing cron plugin

    @pytest.mark.asyncio
    async def test_start_enabled_with_cron(self, tmp_path):
        prompt_file = tmp_path / "HEARTBEAT.md"
        prompt_file.write_text("Do heartbeat stuff")

        mock_cron = Mock()
        mock_cron.add_job = Mock()

        plugin = create_plugin()
        plugin.configure(
            {
                "heartbeat": {
                    "enabled": True,
                    "interval_minutes": 20,
                    "prompt_file": str(prompt_file),
                }
            }
        )
        plugin._registry = Mock()
        plugin._registry.get.return_value = mock_cron

        await plugin.start()

        mock_cron.add_job.assert_called_once()
        job_config = mock_cron.add_job.call_args[0][0]
        assert job_config["name"] == "__heartbeat__"
        assert job_config["schedule"] == "20m"
        assert job_config["mode"] == "main_session"

    @pytest.mark.asyncio
    async def test_start_creates_default_prompt(self, tmp_path):
        prompt_file = tmp_path / "nonexistent" / "HEARTBEAT.md"

        mock_cron = Mock()
        mock_cron.add_job = Mock()

        mock_config = Mock()
        mock_config.get_config.return_value = Mock(config_dir=str(tmp_path))

        def registry_get(name):
            if name == "cron":
                return mock_cron
            if name == "config":
                return mock_config
            return None

        plugin = create_plugin()
        plugin.configure(
            {
                "heartbeat": {
                    "enabled": True,
                    "prompt_file": str(prompt_file),
                }
            }
        )
        plugin._registry = Mock()
        plugin._registry.get.side_effect = registry_get

        await plugin.start()

        # Should create default prompt file
        assert prompt_file.exists()
        assert "HEARTBEAT_OK" in prompt_file.read_text()

    @pytest.mark.asyncio
    async def test_stop_disabled(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.stop()
        # Should not crash

    @pytest.mark.asyncio
    async def test_stop_removes_job(self):
        mock_cron = Mock()
        mock_cron.remove_job = Mock()

        plugin = create_plugin()
        plugin._enabled = True
        plugin._registry = Mock()
        plugin._registry.get.return_value = mock_cron

        await plugin.stop()
        mock_cron.remove_job.assert_called_once_with("__heartbeat__")
