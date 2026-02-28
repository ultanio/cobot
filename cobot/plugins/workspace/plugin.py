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

    # Template files created on workspace init
    TEMPLATES = {
        "AGENTS.md": (
            "# AGENTS.md\n\n"
            "Instructions for AI agents working in this workspace.\n\n"
            "## Role\n\n"
            "Describe your agent's role and responsibilities here.\n\n"
            "## Guidelines\n\n"
            "- Ask before taking irreversible actions\n"
            "- Write things down — no mental notes\n"
            "- Document important decisions\n"
        ),
        "SOUL.md": (
            "# SOUL.md\n\n"
            "Define your agent's identity and personality.\n\n"
            "## Identity\n\n"
            "- **Name:** (pick a name)\n"
            "- **Role:** (what do you do?)\n\n"
            "## Traits\n\n"
            "- Helpful\n"
            "- Careful\n"
            "- Collaborative\n"
        ),
        "USER.md": (
            "# USER.md\n\n"
            "Information about the human you work with.\n\n"
            "- **Name:** \n"
            "- **Timezone:** \n"
            "- **Notes:** \n"
        ),
        "MEMORY.md": (
            "# MEMORY.md\n\n"
            "Long-term memory. Updated periodically from daily notes.\n\n"
            "---\n\n"
            "## Key Facts\n\n"
            "## Lessons Learned\n"
        ),
        "BOOTSTRAP.md": (
            "# BOOTSTRAP.md\n\n"
            "First-run instructions. Follow these steps, then delete this file.\n\n"
            "## Steps\n\n"
            "1. Read SOUL.md — this is who you are\n"
            "2. Read USER.md — this is who you help\n"
            "3. Fill in IDENTITY.md with your chosen identity\n"
            "4. Introduce yourself to your human\n"
            "5. Delete this file when done\n"
        ),
        "IDENTITY.md": (
            "# IDENTITY.md\n\n"
            "Fill this in during your first conversation.\n\n"
            "- **Name:** (pick something you like)\n"
            "- **Creature:** (AI? robot? familiar? something weirder?)\n"
            "- **Vibe:** (sharp? warm? chaotic? calm?)\n"
            "- **Emoji:** (your signature — pick one that feels right)\n"
        ),
    }

    async def start(self) -> None:
        """Create workspace directories and template files if missing."""
        self._workspace.mkdir(parents=True, exist_ok=True)

        # Create standard subdirectories
        subdirs = ["memory", "skills", "plugins", "logs"]
        for subdir in subdirs:
            (self._workspace / subdir).mkdir(exist_ok=True)

        # Create template files (only if they don't exist)
        templates_created = []
        for filename, content in self.TEMPLATES.items():
            filepath = self._workspace / filename
            if not filepath.exists():
                filepath.write_text(content)
                templates_created.append(filename)

        if templates_created:
            self.log_info(f"Created templates: {', '.join(templates_created)}")

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
