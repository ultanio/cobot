"""Heartbeat plugin - periodic main session wake-up.

A convenience wrapper around the cron plugin for the common pattern
of periodic agent wake-up with full session context.

Priority: 45 (after cron)
Dependencies: cron
"""

from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta


class HeartbeatPlugin(Plugin):
    """Heartbeat plugin - convenience wrapper for periodic main session jobs."""

    meta = PluginMeta(
        id="heartbeat",
        version="1.0.0",
        capabilities=[],
        dependencies=["cron"],
        priority=45,
    )

    def __init__(self):
        self._enabled: bool = False
        self._interval_minutes: int = 15
        self._prompt_file: str = "HEARTBEAT.md"
        self._quiet_hours: Optional[str] = None
        self._job_name: str = "__heartbeat__"

    def configure(self, config: dict) -> None:
        """Configure heartbeat settings."""
        hb_config = config.get("heartbeat", {})
        self._enabled = hb_config.get("enabled", False)
        self._interval_minutes = hb_config.get("interval_minutes", 15)
        self._prompt_file = hb_config.get("prompt_file", "HEARTBEAT.md")
        self._quiet_hours = hb_config.get("quiet_hours")

    async def start(self) -> None:
        """Register heartbeat job with cron plugin."""
        if not self._enabled:
            self.log_info("Disabled")
            return

        cron = self._registry.get("cron") if self._registry else None
        if not cron:
            self.log_error("cron plugin not available")
            return

        # Check if prompt file exists
        prompt_path = Path(self._prompt_file).expanduser()
        if not prompt_path.exists():
            # Try relative to config directory
            config_plugin = self._registry.get("config") if self._registry else None
            if config_plugin:
                config_dir = Path(config_plugin.get_config().config_dir)
                prompt_path = config_dir / self._prompt_file

        if not prompt_path.exists():
            self.log_warn(f"prompt file not found: {self._prompt_file}")
            # Create a default HEARTBEAT.md
            default_prompt = """## Heartbeat Check

This is a periodic heartbeat. Do useful maintenance work:

1. Check your inbox for new messages
2. Review any pending tasks
3. Commit workspace changes if needed
4. Update memory with important learnings

If nothing needs attention, respond with: HEARTBEAT_OK
"""
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(default_prompt)
            self.log_info(f"Created default: {prompt_path}")

        # Add heartbeat job to cron
        cron.add_job(
            {
                "name": self._job_name,
                "schedule": f"{self._interval_minutes}m",
                "mode": "main_session",
                "prompt_file": str(prompt_path),
                "quiet_hours": self._quiet_hours,
                "enabled": True,
            }
        )

        self.log_info(f"Enabled (every {self._interval_minutes}m)")

    async def stop(self) -> None:
        """Remove heartbeat job from cron."""
        if not self._enabled:
            return

        cron = self._registry.get("cron") if self._registry else None
        if cron:
            cron.remove_job(self._job_name)


def create_plugin() -> HeartbeatPlugin:
    """Factory function to create the plugin."""
    return HeartbeatPlugin()
