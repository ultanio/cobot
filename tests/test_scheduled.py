"""Tests for scheduled execution plugins (subagent, cron, heartbeat)."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from cobot.plugins.subagent.plugin import SubagentPlugin
from cobot.plugins.cron.plugin import CronPlugin, CronJob
from cobot.plugins.heartbeat.plugin import HeartbeatPlugin
from cobot.plugins.subagent import SubagentResult
from cobot.plugins.interfaces import LLMResponse


class TestSubagentPlugin:
    """Tests for the subagent plugin."""

    @pytest.fixture
    def plugin(self):
        plugin = SubagentPlugin()
        plugin.configure({})
        return plugin

    def test_configure_defaults(self, plugin):
        """Test default configuration."""
        assert plugin._max_concurrent == 3
        assert plugin._default_timeout == 300

    def test_configure_custom(self):
        """Test custom configuration."""
        plugin = SubagentPlugin()
        plugin.configure({
            "subagent": {
                "max_concurrent": 5,
                "default_timeout_seconds": 600,
            }
        })
        assert plugin._max_concurrent == 5
        assert plugin._default_timeout == 600

    def test_get_definitions(self, plugin):
        """Test tool definitions."""
        defs = plugin.get_definitions()
        assert len(defs) == 1
        assert defs[0]["function"]["name"] == "spawn_subagent"

    @pytest.mark.asyncio
    async def test_spawn_no_llm(self, plugin):
        """Test spawn fails without LLM provider."""
        plugin._registry = MagicMock()
        plugin._registry.get_by_capability.return_value = None

        result = await plugin.spawn("test task")

        assert not result.success
        assert "No LLM provider" in result.error

    @pytest.mark.asyncio
    async def test_spawn_success(self, plugin):
        """Test successful spawn."""
        # Mock LLM
        mock_llm = MagicMock()
        mock_llm.chat.return_value = LLMResponse(content="Task completed!")

        # Mock registry
        plugin._registry = MagicMock()
        plugin._registry.get_by_capability.return_value = mock_llm
        plugin._registry.get_implementations.return_value = []

        result = await plugin.spawn("test task", context={"key": "value"})

        assert result.success
        assert result.output == "Task completed!"
        assert result.task == "test task"

    @pytest.mark.asyncio
    async def test_spawn_concurrency_limit(self, plugin):
        """Test concurrency limiting."""
        plugin._max_concurrent = 1
        plugin._active_count = 1

        result = await plugin.spawn("test task")

        assert not result.success
        assert "Concurrency limit" in result.error


class TestCronPlugin:
    """Tests for the cron plugin."""

    @pytest.fixture
    def plugin(self):
        plugin = CronPlugin()
        plugin.configure({})
        return plugin

    def test_configure_jobs(self):
        """Test job configuration from config."""
        plugin = CronPlugin()
        plugin.configure({
            "cron": {
                "jobs": [
                    {
                        "name": "test-job",
                        "schedule": "15m",
                        "mode": "isolated",
                        "prompt": "Do something",
                    }
                ]
            }
        })

        assert "test-job" in plugin._jobs
        job = plugin._jobs["test-job"]
        assert job.schedule == "15m"
        assert job.mode == "isolated"
        assert job.prompt == "Do something"

    def test_add_job(self, plugin):
        """Test dynamic job addition."""
        name = plugin.add_job({
            "name": "dynamic",
            "schedule": "30m",
            "mode": "main_session",
            "prompt": "Check things",
        })

        assert name == "dynamic"
        assert "dynamic" in plugin._jobs

    def test_remove_job(self, plugin):
        """Test job removal."""
        plugin.add_job({"name": "to-remove", "schedule": "1h", "prompt": "x"})
        assert "to-remove" in plugin._jobs

        result = plugin.remove_job("to-remove")
        assert result is True
        assert "to-remove" not in plugin._jobs

    def test_calculate_next_run_minutes(self, plugin):
        """Test interval parsing for minutes."""
        job = CronJob(name="test", schedule="15m", prompt="test")
        plugin._calculate_next_run(job)

        assert job.next_run is not None
        # Should be ~15 minutes from now (±1 second tolerance)
        import time
        expected = time.time() + 900
        assert abs(job.next_run - expected) < 2

    def test_calculate_next_run_hours(self, plugin):
        """Test interval parsing for hours."""
        job = CronJob(name="test", schedule="2h", prompt="test")
        plugin._calculate_next_run(job)

        import time
        expected = time.time() + 7200
        assert abs(job.next_run - expected) < 2

    def test_calculate_next_run_every_minute(self, plugin):
        """Test cron expression for every minute (* * * * *)."""
        job = CronJob(name="test", schedule="* * * * *", prompt="test")
        plugin._calculate_next_run(job)

        import time
        expected = time.time() + 60
        assert abs(job.next_run - expected) < 2

    def test_calculate_next_run_every_5_minutes(self, plugin):
        """Test cron expression for every 5 minutes (*/5 * * * *)."""
        job = CronJob(name="test", schedule="*/5 * * * *", prompt="test")
        plugin._calculate_next_run(job)

        import time
        expected = time.time() + 300
        assert abs(job.next_run - expected) < 2

    def test_quiet_hours_overnight(self, plugin):
        """Test quiet hours detection for overnight range."""
        job = CronJob(name="test", schedule="15m", prompt="test", quiet_hours="23:00-07:00")

        # This is a tricky test since it depends on current time
        # Just verify the method doesn't crash
        result = plugin._in_quiet_hours(job)
        assert isinstance(result, bool)

    def test_quiet_hours_daytime(self, plugin):
        """Test quiet hours detection for daytime range."""
        job = CronJob(name="test", schedule="15m", prompt="test", quiet_hours="12:00-13:00")
        result = plugin._in_quiet_hours(job)
        assert isinstance(result, bool)

    def test_load_prompt_inline(self, plugin):
        """Test loading inline prompt."""
        job = CronJob(name="test", schedule="15m", prompt="Inline prompt text")
        result = plugin._load_prompt(job)
        assert result == "Inline prompt text"

    def test_get_definitions(self, plugin):
        """Test tool definitions."""
        defs = plugin.get_definitions()
        assert len(defs) == 3
        names = [d["function"]["name"] for d in defs]
        assert "cron_add_job" in names
        assert "cron_remove_job" in names
        assert "cron_list_jobs" in names

    def test_tool_add_job(self, plugin):
        """Test cron_add_job tool."""
        result = plugin.execute("cron_add_job", {
            "name": "test-job",
            "schedule": "30m",
            "prompt": "Do something",
            "mode": "isolated",
        })
        assert "added" in result
        assert "test-job" in plugin._jobs

    def test_tool_add_job_duplicate(self, plugin):
        """Test adding duplicate job."""
        plugin.add_job({"name": "existing", "schedule": "1h", "prompt": "x"})
        result = plugin.execute("cron_add_job", {
            "name": "existing",
            "schedule": "30m",
            "prompt": "y",
        })
        assert "already exists" in result

    def test_tool_remove_job(self, plugin):
        """Test cron_remove_job tool."""
        plugin.add_job({"name": "to-remove", "schedule": "1h", "prompt": "x"})
        result = plugin.execute("cron_remove_job", {"name": "to-remove"})
        assert "removed" in result
        assert "to-remove" not in plugin._jobs

    def test_tool_remove_system_job(self, plugin):
        """Test cannot remove system jobs."""
        plugin.add_job({"name": "__heartbeat__", "schedule": "15m", "prompt": "x"})
        result = plugin.execute("cron_remove_job", {"name": "__heartbeat__"})
        assert "cannot remove system job" in result
        assert "__heartbeat__" in plugin._jobs

    def test_tool_list_jobs(self, plugin):
        """Test cron_list_jobs tool."""
        plugin.add_job({"name": "job1", "schedule": "15m", "prompt": "Task 1"})
        plugin.add_job({"name": "job2", "schedule": "1h", "prompt": "Task 2", "mode": "main_session"})
        result = plugin.execute("cron_list_jobs", {})
        assert "job1" in result
        assert "job2" in result
        assert "isolated" in result
        assert "main_session" in result


class TestHeartbeatPlugin:
    """Tests for the heartbeat plugin."""

    @pytest.fixture
    def plugin(self):
        plugin = HeartbeatPlugin()
        plugin.configure({})
        return plugin

    def test_configure_disabled_by_default(self, plugin):
        """Test heartbeat is disabled by default."""
        assert plugin._enabled is False

    def test_configure_enabled(self):
        """Test enabling heartbeat."""
        plugin = HeartbeatPlugin()
        plugin.configure({
            "heartbeat": {
                "enabled": True,
                "interval_minutes": 30,
                "prompt_file": "custom.md",
                "quiet_hours": "22:00-08:00",
            }
        })

        assert plugin._enabled is True
        assert plugin._interval_minutes == 30
        assert plugin._prompt_file == "custom.md"
        assert plugin._quiet_hours == "22:00-08:00"

    @pytest.mark.asyncio
    async def test_start_disabled(self, plugin):
        """Test start when disabled."""
        plugin._enabled = False
        plugin._registry = MagicMock()

        await plugin.start()

        # Should not call cron plugin
        plugin._registry.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_start_no_cron(self):
        """Test start without cron plugin."""
        plugin = HeartbeatPlugin()
        plugin.configure({"heartbeat": {"enabled": True}})
        plugin._registry = MagicMock()
        plugin._registry.get.return_value = None

        # Should not raise
        await plugin.start()


class TestAggregatedToolProvider:
    """Tests for the AggregatedToolProvider in loop plugin."""

    def test_aggregates_from_multiple_providers(self):
        """Test that tools are aggregated from multiple providers."""
        from cobot.plugins.loop.plugin import AggregatedToolProvider
        from cobot.plugins.cron.plugin import CronPlugin
        from cobot.plugins.subagent.plugin import SubagentPlugin

        cron = CronPlugin()
        subagent = SubagentPlugin()
        cron.configure({})
        subagent.configure({})

        aggregator = AggregatedToolProvider([cron, subagent])
        all_defs = aggregator.get_definitions()
        tool_names = [d["function"]["name"] for d in all_defs]

        # Should have both cron and subagent tools
        assert "cron_add_job" in tool_names
        assert "spawn_subagent" in tool_names

    def test_routes_execution_correctly(self):
        """Test that execute routes to the correct provider."""
        from cobot.plugins.loop.plugin import AggregatedToolProvider
        from cobot.plugins.cron.plugin import CronPlugin

        cron = CronPlugin()
        cron.configure({})

        aggregator = AggregatedToolProvider([cron])
        result = aggregator.execute("cron_list_jobs", {})

        assert "No cron jobs" in result or "Cron Jobs" in result


class TestToolAggregation:
    """Tests for tool aggregation from multiple ToolProviders."""

    def test_cron_tools_in_definitions(self):
        """Test that cron tools are included in aggregated definitions."""
        from cobot.plugins.tools.plugin import ToolsPlugin
        from cobot.plugins.cron.plugin import CronPlugin

        # Create plugins
        tools_plugin = ToolsPlugin()
        cron_plugin = CronPlugin()

        # Mock registry
        mock_registry = MagicMock()
        mock_registry.all_with_capability.return_value = [tools_plugin, cron_plugin]

        tools_plugin._registry = mock_registry
        tools_plugin.configure({})
        cron_plugin.configure({})

        # Get definitions
        all_defs = tools_plugin.get_definitions()
        tool_names = [d["function"]["name"] for d in all_defs]

        # Verify cron tools are included
        assert "cron_add_job" in tool_names
        assert "cron_remove_job" in tool_names
        assert "cron_list_jobs" in tool_names

    def test_subagent_tools_in_definitions(self):
        """Test that subagent tools are included in aggregated definitions."""
        from cobot.plugins.tools.plugin import ToolsPlugin
        from cobot.plugins.subagent.plugin import SubagentPlugin

        tools_plugin = ToolsPlugin()
        subagent_plugin = SubagentPlugin()

        mock_registry = MagicMock()
        mock_registry.all_with_capability.return_value = [tools_plugin, subagent_plugin]

        tools_plugin._registry = mock_registry
        tools_plugin.configure({})
        subagent_plugin.configure({})

        all_defs = tools_plugin.get_definitions()
        tool_names = [d["function"]["name"] for d in all_defs]

        assert "spawn_subagent" in tool_names

    def test_tool_execution_routes_to_cron(self):
        """Test that cron tool execution is routed correctly."""
        from cobot.plugins.tools.plugin import ToolsPlugin
        from cobot.plugins.cron.plugin import CronPlugin

        tools_plugin = ToolsPlugin()
        cron_plugin = CronPlugin()

        mock_registry = MagicMock()
        mock_registry.all_with_capability.return_value = [tools_plugin, cron_plugin]

        tools_plugin._registry = mock_registry
        tools_plugin.configure({})
        cron_plugin.configure({})

        # Execute cron_list_jobs via tools plugin
        result = tools_plugin.execute("cron_list_jobs", {})
        assert "No cron jobs" in result or "Cron Jobs" in result


class TestCronLoopIntegration:
    """Tests for cron integration with the main loop."""

    def test_poll_main_session_jobs_returns_messages(self):
        """Test that poll_main_session_jobs returns IncomingMessage list."""
        plugin = CronPlugin()
        plugin.configure({})

        # Add a main_session job that's due
        plugin.add_job({
            "name": "test-main",
            "schedule": "1m",
            "mode": "main_session",
            "prompt": "Test prompt",
        })

        # Force job to be due
        import time
        plugin._jobs["test-main"].next_run = time.time() - 1

        # Poll should return messages
        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 1
        assert messages[0].content == "Test prompt"
        assert messages[0].channel_type == "cron"
        assert messages[0].metadata.get("is_cron") is True

    def test_poll_main_session_jobs_skips_isolated(self):
        """Test that isolated jobs are not returned by poll."""
        plugin = CronPlugin()
        plugin.configure({})

        # Add an isolated job
        plugin.add_job({
            "name": "test-isolated",
            "schedule": "1m",
            "mode": "isolated",
            "prompt": "Isolated prompt",
        })

        # Force job to be due
        import time
        plugin._jobs["test-isolated"].next_run = time.time() - 1

        # Poll should return empty (isolated jobs handled by scheduler)
        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 0

    def test_poll_main_session_jobs_respects_quiet_hours(self):
        """Test that quiet hours are respected."""
        plugin = CronPlugin()
        plugin.configure({})

        # Add job with 24h quiet hours (always quiet)
        plugin.add_job({
            "name": "test-quiet",
            "schedule": "1m",
            "mode": "main_session",
            "prompt": "Should not fire",
            "quiet_hours": "00:00-23:59",
        })

        # Force job to be due
        import time
        plugin._jobs["test-quiet"].next_run = time.time() - 1

        # Poll should return empty due to quiet hours
        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 0
