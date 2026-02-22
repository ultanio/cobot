"""Workspace plugin - provides workspace directory paths.

Priority: 5 (very early - other plugins depend on it)
Capability: workspace

Workspace location priority:
1. CLI argument (_cli_workspace in config)
2. COBOT_WORKSPACE environment variable
3. workspace: in config
4. Default: ~/.cobot/workspace/
"""

import os
from pathlib import Path

from ..base import Plugin, PluginMeta


class WorkspacePlugin(Plugin):
    """Workspace directory provider plugin."""

    meta = PluginMeta(
        id="workspace",
        version="1.0.0",
        capabilities=["workspace"],
        dependencies=["config"],
        priority=5,  # Load very early
    )

    def __init__(self):
        self._workspace: Path = Path.home() / ".cobot" / "workspace"

    def configure(self, config: dict) -> None:
        """Resolve workspace path with priority: CLI > env > config > default."""
        # Priority 1: CLI argument (passed as _cli_workspace)
        cli_workspace = config.get("_cli_workspace")

        # Priority 2: Environment variable
        env_workspace = os.environ.get("COBOT_WORKSPACE")

        # Priority 3: Config file
        config_workspace = config.get("workspace")

        # Priority 4: Default
        default_workspace = Path.home() / ".cobot" / "workspace"

        # Resolve with priority
        workspace_str = cli_workspace or env_workspace or config_workspace
        if workspace_str:
            self._workspace = Path(workspace_str).expanduser().resolve()
        else:
            self._workspace = default_workspace

    async def start(self) -> None:
        """Create workspace directories if missing."""
        self._workspace.mkdir(parents=True, exist_ok=True)

        # Create standard subdirectories
        subdirs = ["memory", "skills", "plugins", "logs"]
        for subdir in subdirs:
            (self._workspace / subdir).mkdir(exist_ok=True)

        self.log_info(f"{self._workspace}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def get_path(self, *parts: str) -> Path:
        """Get a path within the workspace.

        Args:
            *parts: Path components relative to workspace root

        Returns:
            Full path within workspace

        Examples:
            get_path() -> /home/user/.cobot/workspace
            get_path("memory") -> /home/user/.cobot/workspace/memory
            get_path("memory", "2026-02-13.md") -> /home/user/.cobot/workspace/memory/2026-02-13.md
        """
        if parts:
            return self._workspace / Path(*parts)
        return self._workspace


def create_plugin() -> WorkspacePlugin:
    """Factory function for plugin discovery."""
    return WorkspacePlugin()
