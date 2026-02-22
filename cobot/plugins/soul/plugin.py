"""Soul plugin - persona and tone from SOUL.md.

Reads SOUL.md from workspace to define agent persona.
Implements context.system_prompt extension point.

Priority: 15 (after workspace)
"""

from pathlib import Path

from ..base import Plugin, PluginMeta


class SoulPlugin(Plugin):
    """Soul/persona plugin - reads SOUL.md from workspace."""

    meta = PluginMeta(
        id="soul",
        version="1.0.0",
        dependencies=["workspace"],
        implements={
            "context.system_prompt": "get_soul",
        },
        priority=15,
    )

    def __init__(self):
        self._workspace_path: Path = Path(".")
        self._soul: str = ""
        self._registry = None  # Set by registry when registered

    def configure(self, config: dict) -> None:
        """Get workspace path from config or workspace plugin."""
        # Can be passed directly for testing
        if "_workspace_path" in config:
            self._workspace_path = Path(config["_workspace_path"])

    async def start(self) -> None:
        """Load SOUL.md from workspace."""
        # Try to get workspace from registry if available
        if self._registry:
            try:
                workspace = self._registry.get_plugin("workspace")
                if workspace:
                    self._workspace_path = workspace.get_path()
            except Exception:
                pass

        soul_path = self._workspace_path / "SOUL.md"
        if soul_path.exists():
            self._soul = soul_path.read_text()
            self.log_info(f"Loaded from {soul_path}")
        else:
            self._soul = ""

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def get_soul(self) -> str:
        """Get the soul/persona content.

        Returns:
            Content of SOUL.md or empty string if not found.
        """
        return self._soul


def create_plugin() -> SoulPlugin:
    """Factory function for plugin discovery."""
    return SoulPlugin()
