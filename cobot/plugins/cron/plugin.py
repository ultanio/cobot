"""Cron plugin - scheduled job execution.

Supports two execution modes:
- isolated: Spawns subagent (no context)
- main_session: Injects into main session (full context)

Priority: 40 (after subagent)
"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import click

from ..base import Plugin, PluginMeta
from ..interfaces import ToolProvider
from ..communication import IncomingMessage


# Tool definitions for agent use
CRON_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "cron_add_job",
            "description": (
                "Add a scheduled cron job. Jobs can run in 'isolated' mode (spawns subagent) "
                "or 'main_session' mode (injects into main session with full context)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Unique job name",
                    },
                    "schedule": {
                        "type": "string",
                        "description": "Schedule: interval (e.g., '15m', '1h') or cron expression (e.g., '0 9 * * *')",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Task prompt for the job",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["isolated", "main_session"],
                        "default": "isolated",
                        "description": "Execution mode: 'isolated' (no context) or 'main_session' (full context)",
                    },
                },
                "required": ["name", "schedule", "prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cron_remove_job",
            "description": "Remove a scheduled cron job by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the job to remove",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cron_list_jobs",
            "description": "List all scheduled cron jobs.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


@dataclass
class CronJob:
    """Configuration for a cron job."""

    name: str
    schedule: str  # Cron expression or interval (e.g., "*/15 * * * *" or "15m")
    mode: str = "isolated"  # "isolated" or "main_session"
    prompt: Optional[str] = None
    prompt_file: Optional[str] = None
    system_prompt: Optional[str] = None
    quiet_hours: Optional[str] = None  # e.g., "23:00-07:00"
    output: dict = field(default_factory=dict)  # Output routing config
    enabled: bool = True

    # Runtime state
    last_run: Optional[float] = None
    next_run: Optional[float] = None


class CronPlugin(Plugin, ToolProvider):
    """Cron plugin for scheduled job execution."""

    meta = PluginMeta(
        id="cron",
        version="1.0.0",
        capabilities=["cron", "tools"],
        dependencies=["config"],
        priority=40,
        extension_points=[
            "cron.before_job",  # Modify job before execution
            "cron.after_job",  # Process result after execution
        ],
        implements={
            "session.poll_messages": "poll_main_session_jobs",
        },
    )

    def __init__(self):
        self._config: dict = {}
        self._jobs: dict[str, CronJob] = {}
        self._scheduler_task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._restart_requested: bool = False

    def configure(self, config: dict) -> None:
        """Configure cron jobs from config."""
        cron_config = config.get("cron", {})
        self._config = cron_config

        # Parse jobs from config
        for job_cfg in cron_config.get("jobs", []):
            job = CronJob(
                name=job_cfg.get("name", f"job_{len(self._jobs)}"),
                schedule=job_cfg.get("schedule", "*/15 * * * *"),
                mode=job_cfg.get("mode", "isolated"),
                prompt=job_cfg.get("prompt"),
                prompt_file=job_cfg.get("prompt_file"),
                system_prompt=job_cfg.get("system_prompt"),
                quiet_hours=job_cfg.get("quiet_hours"),
                output=job_cfg.get("output", {}),
                enabled=job_cfg.get("enabled", True),
            )
            self._jobs[job.name] = job
            self._calculate_next_run(job)

    async def start(self) -> None:
        """Start the cron scheduler."""
        self._running = True
        self._scheduler_task = asyncio.create_task(self._run_scheduler())
        self.log_info(f"Started with {len(self._jobs)} job(s)")

    async def stop(self) -> None:
        """Stop the cron scheduler."""
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass

    def add_job(self, job_config: dict) -> str:
        """Add a job dynamically (used by heartbeat plugin)."""
        job = CronJob(
            name=job_config.get("name", f"dynamic_{len(self._jobs)}"),
            schedule=job_config.get("schedule", "*/15 * * * *"),
            mode=job_config.get("mode", "isolated"),
            prompt=job_config.get("prompt"),
            prompt_file=job_config.get("prompt_file"),
            system_prompt=job_config.get("system_prompt"),
            quiet_hours=job_config.get("quiet_hours"),
            output=job_config.get("output", {}),
            enabled=job_config.get("enabled", True),
        )
        self._jobs[job.name] = job
        self._calculate_next_run(job)
        self.log_info(f"Added job: {job.name}")
        return job.name

    def remove_job(self, name: str) -> bool:
        """Remove a job."""
        if name in self._jobs:
            del self._jobs[name]
            return True
        return False

    # --- Scheduler ---

    async def _run_scheduler(self) -> None:
        """Background scheduler loop for isolated jobs."""
        while self._running:
            now = time.time()

            for job in list(self._jobs.values()):
                if not job.enabled:
                    continue
                if job.mode != "isolated":
                    continue  # main_session jobs handled via poll
                if job.next_run and now >= job.next_run:
                    if not self._in_quiet_hours(job):
                        asyncio.create_task(self._run_isolated_job(job))
                    job.last_run = now
                    self._calculate_next_run(job)

            await asyncio.sleep(30)  # Check every 30 seconds

    async def _run_isolated_job(self, job: CronJob) -> None:
        """Run a job in isolated mode via subagent."""
        self.log_info(f"Running isolated job: {job.name}")

        # Get subagent provider
        subagent = self._registry.get("subagent") if self._registry else None
        if not subagent:
            self.log_error("subagent plugin not available")
            return

        # Load prompt
        prompt = self._load_prompt(job)
        if not prompt:
            self.log_error(f"no prompt for job {job.name}")
            return

        # Call extension point
        ctx = {"job": job, "prompt": prompt}
        await self.call_extension("cron.before_job", ctx)

        # Spawn subagent
        result = await subagent.spawn(
            task=ctx.get("prompt", prompt),
            system_prompt=job.system_prompt,
            timeout_seconds=300,
        )

        # Route output
        await self._route_output(job, result.output if result.success else result.error)

        # Call extension point
        await self.call_extension("cron.after_job", {"job": job, "result": result})

    # --- Main Session Integration ---

    def poll_main_session_jobs(self) -> list[IncomingMessage]:
        """Poll for main_session jobs that are due (implements session.poll_messages)."""
        messages = []
        now = time.time()

        for job in list(self._jobs.values()):
            if not job.enabled:
                continue
            if job.mode != "main_session":
                continue
            if job.next_run and now >= job.next_run:
                if not self._in_quiet_hours(job):
                    msg = self._create_message(job)
                    if msg:
                        messages.append(msg)
                job.last_run = now
                self._calculate_next_run(job)

        return messages

    def _create_message(self, job: CronJob) -> Optional[IncomingMessage]:
        """Create an IncomingMessage for a main_session job."""
        prompt = self._load_prompt(job)
        if not prompt:
            return None

        return IncomingMessage(
            id=f"cron-{job.name}-{int(time.time())}",
            channel_type="cron",
            channel_id=job.name,
            sender_id="system",
            sender_name="Cron",
            content=prompt,
            timestamp=datetime.now(),
            metadata={
                "is_cron": True,
                "job_name": job.name,
                "skip_persistence": True,  # Don't save cron messages to history
            },
        )

    # --- Helpers ---

    def _load_prompt(self, job: CronJob) -> Optional[str]:
        """Load prompt from inline or file."""
        if job.prompt:
            return job.prompt

        if job.prompt_file:
            path = Path(job.prompt_file).expanduser()
            if path.exists():
                return path.read_text().strip()
            else:
                self.log_warn(f"prompt_file not found: {path}")

        return None

    def _calculate_next_run(self, job: CronJob) -> None:
        """Calculate next run time from schedule."""
        now = time.time()

        # Parse schedule - support simple intervals first
        schedule = job.schedule.strip()

        if schedule.endswith("m"):
            # Simple interval: "15m" = every 15 minutes
            try:
                minutes = int(schedule[:-1])
                job.next_run = now + (minutes * 60)
                return
            except ValueError:
                pass

        if schedule.endswith("h"):
            # Simple interval: "1h" = every hour
            try:
                hours = int(schedule[:-1])
                job.next_run = now + (hours * 3600)
                return
            except ValueError:
                pass

        # Cron expression - basic parsing for common patterns
        # Format: minute hour day month weekday
        parts = schedule.split()
        if len(parts) == 5:
            minute, hour, day, month, weekday = parts

            # Handle * (every minute)
            if minute == "*":
                job.next_run = now + 60
                return

            # Handle */N patterns
            if minute.startswith("*/"):
                try:
                    interval = int(minute[2:])
                    job.next_run = now + (interval * 60)
                    return
                except ValueError:
                    pass

            # Handle specific minute (e.g., "0" for top of hour)
            try:
                target_minute = int(minute)
                current = datetime.fromtimestamp(now)
                if current.minute < target_minute:
                    # Later this hour
                    job.next_run = now + (target_minute - current.minute) * 60
                else:
                    # Next hour
                    job.next_run = now + (60 - current.minute + target_minute) * 60
                return
            except ValueError:
                pass

        # Default: 15 minutes
        job.next_run = now + 900

    def _in_quiet_hours(self, job: CronJob) -> bool:
        """Check if current time is in quiet hours."""
        if not job.quiet_hours:
            return False

        try:
            start_str, end_str = job.quiet_hours.split("-")
            start_h, start_m = map(int, start_str.split(":"))
            end_h, end_m = map(int, end_str.split(":"))

            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_h * 60 + start_m
            end_minutes = end_h * 60 + end_m

            if start_minutes <= end_minutes:
                # Same day range (e.g., 09:00-17:00)
                return start_minutes <= current_minutes < end_minutes
            else:
                # Overnight range (e.g., 23:00-07:00)
                return current_minutes >= start_minutes or current_minutes < end_minutes

        except Exception:
            return False

    async def _route_output(self, job: CronJob, content: str) -> None:
        """Route job output to configured destination."""
        output_cfg = job.output
        output_type = output_cfg.get("type", "log")

        if output_type == "log":
            self.log_info(f"{job.name}: {content[:200]}...")

        elif output_type == "file":
            target = output_cfg.get("target", f"/tmp/cron-{job.name}.txt")
            Path(target).expanduser().write_text(content)

        elif output_type == "telegram":
            comm = self._registry.get("communication") if self._registry else None
            if comm:
                from ..communication import OutgoingMessage

                comm.send(
                    OutgoingMessage(
                        channel_type="telegram",
                        channel_id=output_cfg.get("target", ""),
                        content=f"**[Cron: {job.name}]**\n{content}",
                    )
                )

        elif output_type == "filedrop":
            filedrop = self._registry.get("filedrop") if self._registry else None
            if filedrop:
                filedrop.send(output_cfg.get("target", ""), content)

    # --- ToolProvider Interface ---

    def get_definitions(self) -> list[dict]:
        """Get tool definitions."""
        return CRON_TOOLS

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a cron tool."""
        if tool_name == "cron_add_job":
            return self._tool_add_job(args)
        elif tool_name == "cron_remove_job":
            return self._tool_remove_job(args)
        elif tool_name == "cron_list_jobs":
            return self._tool_list_jobs()
        return f"Unknown tool: {tool_name}"

    @property
    def restart_requested(self) -> bool:
        """Check if restart was requested."""
        return self._restart_requested

    def _tool_add_job(self, args: dict) -> str:
        """Execute cron_add_job tool."""
        name = args.get("name", "")
        schedule = args.get("schedule", "")
        prompt = args.get("prompt", "")
        mode = args.get("mode", "isolated")

        if not name or not schedule or not prompt:
            return "Error: name, schedule, and prompt are required"

        if name in self._jobs:
            return f"Error: job '{name}' already exists"

        self.add_job(
            {
                "name": name,
                "schedule": schedule,
                "prompt": prompt,
                "mode": mode,
                "enabled": True,
            }
        )

        return f"✅ Job '{name}' added (schedule: {schedule}, mode: {mode})"

    def _tool_remove_job(self, args: dict) -> str:
        """Execute cron_remove_job tool."""
        name = args.get("name", "")
        if not name:
            return "Error: name is required"

        if name not in self._jobs:
            return f"Error: job '{name}' not found"

        # Protect system jobs
        if name.startswith("__"):
            return f"Error: cannot remove system job '{name}'"

        self.remove_job(name)
        return f"✅ Job '{name}' removed"

    def _tool_list_jobs(self) -> str:
        """Execute cron_list_jobs tool."""
        if not self._jobs:
            return "No cron jobs configured."

        lines = ["**Cron Jobs:**\n"]
        for name, job in self._jobs.items():
            status = "✅" if job.enabled else "⏸️"
            mode_icon = "🔒" if job.mode == "isolated" else "🏠"
            lines.append(
                f"- {status} **{name}** ({job.schedule}) {mode_icon} {job.mode}"
            )
            if job.prompt:
                preview = (
                    job.prompt[:50] + "..." if len(job.prompt) > 50 else job.prompt
                )
                lines.append(f"  └─ {preview}")

        return "\n".join(lines)

    # --- CLI Commands ---

    def register_commands(self, cli) -> None:
        """Register cron CLI commands."""
        plugin = self  # Capture for closures

        @cli.group()
        def cron():
            """Cron job management commands."""
            pass

        @cron.command("list")
        def list_jobs():
            """List all cron jobs."""
            if not plugin._jobs:
                click.echo("No cron jobs configured.")
                return

            click.echo("\nCron Jobs:")
            click.echo("-" * 60)
            for name, job in plugin._jobs.items():
                status = "✓" if job.enabled else "○"
                mode = "isolated" if job.mode == "isolated" else "main"
                next_run = ""
                if job.next_run:
                    from_now = int(job.next_run - time.time())
                    if from_now > 0:
                        mins = from_now // 60
                        next_run = f"(next: {mins}m)"
                click.echo(
                    f"  [{status}] {name:<20} {job.schedule:<12} {mode:<8} {next_run}"
                )
                if job.prompt:
                    preview = (
                        job.prompt[:50] + "..." if len(job.prompt) > 50 else job.prompt
                    )
                    click.echo(f"      └─ {preview}")
            click.echo()

        @cron.command("add")
        @click.argument("name")
        @click.argument("schedule")
        @click.argument("prompt")
        @click.option(
            "--mode",
            "-m",
            type=click.Choice(["isolated", "main_session"]),
            default="isolated",
            help="Execution mode",
        )
        def add_job(name: str, schedule: str, prompt: str, mode: str):
            """Add a cron job.

            NAME: Unique job name
            SCHEDULE: Interval (e.g., '15m', '1h') or cron expression
            PROMPT: Task prompt for the job
            """
            if name in plugin._jobs:
                click.echo(f"Error: job '{name}' already exists", err=True)
                return

            plugin.add_job(
                {
                    "name": name,
                    "schedule": schedule,
                    "prompt": prompt,
                    "mode": mode,
                    "enabled": True,
                }
            )
            click.echo(f"✓ Added job '{name}' (schedule: {schedule}, mode: {mode})")

        @cron.command("remove")
        @click.argument("name")
        def remove_job(name: str):
            """Remove a cron job.

            NAME: Name of the job to remove
            """
            if name not in plugin._jobs:
                click.echo(f"Error: job '{name}' not found", err=True)
                return

            if name.startswith("__"):
                click.echo(f"Error: cannot remove system job '{name}'", err=True)
                return

            plugin.remove_job(name)
            click.echo(f"✓ Removed job '{name}'")

        @cron.command("run")
        @click.argument("name")
        def run_job(name: str):
            """Trigger a job immediately.

            NAME: Name of the job to run
            """
            if name not in plugin._jobs:
                click.echo(f"Error: job '{name}' not found", err=True)
                return

            job = plugin._jobs[name]
            click.echo(f"Triggering job '{name}'...")

            if job.mode == "isolated":
                # Run isolated job
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(asyncio.run, plugin._run_isolated_job(job))
                    future.result()
                click.echo(f"✓ Job '{name}' completed")
            else:
                # Force next_run to now so it gets picked up
                job.next_run = time.time() - 1
                click.echo(f"✓ Job '{name}' scheduled for next poll")

        @cron.command("enable")
        @click.argument("name")
        def enable_job(name: str):
            """Enable a disabled job."""
            if name not in plugin._jobs:
                click.echo(f"Error: job '{name}' not found", err=True)
                return
            plugin._jobs[name].enabled = True
            click.echo(f"✓ Enabled job '{name}'")

        @cron.command("disable")
        @click.argument("name")
        def disable_job(name: str):
            """Disable a job (keeps config, stops execution)."""
            if name not in plugin._jobs:
                click.echo(f"Error: job '{name}' not found", err=True)
                return
            plugin._jobs[name].enabled = False
            click.echo(f"✓ Disabled job '{name}'")


def create_plugin() -> CronPlugin:
    """Factory function to create the plugin."""
    return CronPlugin()
