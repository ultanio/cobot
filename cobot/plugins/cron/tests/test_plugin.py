"""Tests for CronPlugin."""

import time

import pytest

from ..plugin import CronPlugin, CronJob, create_plugin


# === Plugin Creation ===


class TestCreatePlugin:
    def test_returns_cron_plugin(self):
        assert isinstance(create_plugin(), CronPlugin)

    def test_new_instance_each_call(self):
        assert create_plugin() is not create_plugin()


# === Meta ===


class TestMeta:
    def test_id(self):
        assert create_plugin().meta.id == "cron"

    def test_capabilities(self):
        meta = create_plugin().meta
        assert "cron" in meta.capabilities
        assert "tools" in meta.capabilities

    def test_priority(self):
        assert create_plugin().meta.priority == 40

    def test_extension_points(self):
        meta = create_plugin().meta
        assert "cron.before_job" in meta.extension_points
        assert "cron.after_job" in meta.extension_points


# === Configuration ===


class TestConfigure:
    def test_empty_config(self):
        plugin = create_plugin()
        plugin.configure({})
        assert len(plugin._jobs) == 0

    def test_single_job(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "cron": {
                    "jobs": [
                        {
                            "name": "test_job",
                            "schedule": "15m",
                            "prompt": "do stuff",
                            "mode": "isolated",
                        }
                    ]
                }
            }
        )
        assert "test_job" in plugin._jobs
        job = plugin._jobs["test_job"]
        assert job.schedule == "15m"
        assert job.prompt == "do stuff"
        assert job.mode == "isolated"

    def test_multiple_jobs(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "cron": {
                    "jobs": [
                        {"name": "a", "schedule": "5m", "prompt": "task a"},
                        {"name": "b", "schedule": "1h", "prompt": "task b"},
                    ]
                }
            }
        )
        assert len(plugin._jobs) == 2

    def test_job_defaults(self):
        plugin = create_plugin()
        plugin.configure({"cron": {"jobs": [{"name": "minimal", "prompt": "test"}]}})
        job = plugin._jobs["minimal"]
        assert job.mode == "isolated"
        assert job.enabled is True
        assert job.quiet_hours is None

    def test_quiet_hours(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "cron": {
                    "jobs": [
                        {
                            "name": "quiet",
                            "schedule": "15m",
                            "prompt": "test",
                            "quiet_hours": "23:00-07:00",
                        }
                    ]
                }
            }
        )
        assert plugin._jobs["quiet"].quiet_hours == "23:00-07:00"


# === Add / Remove Jobs ===


class TestAddRemoveJobs:
    def test_add_job(self):
        plugin = create_plugin()
        plugin.configure({})
        name = plugin.add_job(
            {
                "name": "dynamic",
                "schedule": "10m",
                "prompt": "dynamic task",
            }
        )
        assert name == "dynamic"
        assert "dynamic" in plugin._jobs

    def test_remove_job(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job({"name": "removeme", "schedule": "5m", "prompt": "x"})
        assert plugin.remove_job("removeme") is True
        assert "removeme" not in plugin._jobs

    def test_remove_nonexistent(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin.remove_job("nope") is False


# === Schedule Parsing ===


class TestCalculateNextRun:
    def test_minutes_interval(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="15m")
        plugin._calculate_next_run(job)
        assert job.next_run is not None
        assert job.next_run > time.time()
        assert job.next_run <= time.time() + 15 * 60 + 1

    def test_hours_interval(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="2h")
        plugin._calculate_next_run(job)
        assert job.next_run is not None
        assert job.next_run <= time.time() + 2 * 3600 + 1

    def test_cron_every_minute(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="* * * * *")
        plugin._calculate_next_run(job)
        assert job.next_run <= time.time() + 61

    def test_cron_every_n_minutes(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="*/5 * * * *")
        plugin._calculate_next_run(job)
        assert job.next_run <= time.time() + 5 * 60 + 1

    def test_invalid_defaults_to_15m(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="garbage")
        plugin._calculate_next_run(job)
        assert job.next_run is not None
        assert job.next_run <= time.time() + 901


# === Quiet Hours ===


class TestQuietHours:
    def test_no_quiet_hours(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m")
        assert plugin._in_quiet_hours(job) is False

    def test_invalid_quiet_hours(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m", quiet_hours="invalid")
        assert plugin._in_quiet_hours(job) is False


# === Prompt Loading ===


class TestLoadPrompt:
    def test_inline_prompt(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m", prompt="do this")
        assert plugin._load_prompt(job) == "do this"

    def test_prompt_file(self, tmp_path):
        f = tmp_path / "task.md"
        f.write_text("file prompt content")
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m", prompt_file=str(f))
        assert plugin._load_prompt(job) == "file prompt content"

    def test_missing_prompt_file(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m", prompt_file="/nonexistent.md")
        assert plugin._load_prompt(job) is None

    def test_no_prompt_no_file(self):
        plugin = create_plugin()
        job = CronJob(name="t", schedule="5m")
        assert plugin._load_prompt(job) is None


# === Poll Main Session Jobs ===


class TestPollMainSessionJobs:
    def test_returns_due_main_session_jobs(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job(
            {
                "name": "poll_me",
                "schedule": "5m",
                "mode": "main_session",
                "prompt": "heartbeat check",
            }
        )
        # Force job to be due
        plugin._jobs["poll_me"].next_run = time.time() - 1

        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 1
        assert "heartbeat check" in messages[0].content

    def test_skips_isolated_jobs(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job(
            {
                "name": "isolated_job",
                "schedule": "5m",
                "mode": "isolated",
                "prompt": "should not appear",
            }
        )
        plugin._jobs["isolated_job"].next_run = time.time() - 1

        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 0

    def test_skips_disabled_jobs(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job(
            {
                "name": "disabled_job",
                "schedule": "5m",
                "mode": "main_session",
                "prompt": "nope",
                "enabled": False,
            }
        )
        plugin._jobs["disabled_job"].next_run = time.time() - 1

        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 0

    def test_skips_not_yet_due(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job(
            {
                "name": "future_job",
                "schedule": "5m",
                "mode": "main_session",
                "prompt": "not yet",
            }
        )
        plugin._jobs["future_job"].next_run = time.time() + 9999

        messages = plugin.poll_main_session_jobs()
        assert len(messages) == 0


# === Tool Provider ===


class TestToolProvider:
    def test_get_definitions(self):
        plugin = create_plugin()
        defs = plugin.get_definitions()
        names = [d["function"]["name"] for d in defs]
        assert "cron_add_job" in names
        assert "cron_remove_job" in names
        assert "cron_list_jobs" in names

    def test_add_job_tool(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute(
            "cron_add_job",
            {
                "name": "tooltest",
                "schedule": "10m",
                "prompt": "from tool",
            },
        )
        assert "tooltest" in result
        assert "tooltest" in plugin._jobs

    def test_add_job_missing_fields(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("cron_add_job", {"name": "incomplete"})
        assert "Error" in result

    def test_add_duplicate_job(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job({"name": "dup", "schedule": "5m", "prompt": "x"})
        result = plugin.execute(
            "cron_add_job",
            {
                "name": "dup",
                "schedule": "5m",
                "prompt": "x",
            },
        )
        assert "already exists" in result

    def test_remove_job_tool(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job({"name": "bye", "schedule": "5m", "prompt": "x"})
        result = plugin.execute("cron_remove_job", {"name": "bye"})
        assert "bye" in result
        assert "bye" not in plugin._jobs

    def test_remove_system_job(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job({"name": "__system", "schedule": "5m", "prompt": "x"})
        result = plugin.execute("cron_remove_job", {"name": "__system"})
        assert "cannot remove" in result

    def test_remove_nonexistent_tool(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("cron_remove_job", {"name": "nope"})
        assert "not found" in result

    def test_list_jobs_empty(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("cron_list_jobs", {})
        assert "No cron jobs" in result

    def test_list_jobs_with_jobs(self):
        plugin = create_plugin()
        plugin.configure({})
        plugin.add_job({"name": "listed", "schedule": "5m", "prompt": "task"})
        result = plugin.execute("cron_list_jobs", {})
        assert "listed" in result

    def test_unknown_tool(self):
        plugin = create_plugin()
        result = plugin.execute("nonexistent", {})
        assert "Unknown" in result


# === Lifecycle ===


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.start()
        assert plugin._running is True
        assert plugin._scheduler_task is not None
        await plugin.stop()

    @pytest.mark.asyncio
    async def test_stop(self):
        plugin = create_plugin()
        plugin.configure({})
        await plugin.start()
        await plugin.stop()
        assert plugin._running is False
