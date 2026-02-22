"""Memory-files plugin - file-based memory implementation.

Implements memory extension points using .md files in workspace/memory/files/.

Priority: 14 (after memory extension point definer)
"""

from pathlib import Path

from ..base import Plugin, PluginMeta


class MemoryFilesPlugin(Plugin):
    """File-based memory storage plugin."""

    meta = PluginMeta(
        id="memory-files",
        version="1.0.0",
        dependencies=["workspace", "memory"],
        implements={
            "memory.store": "store",
            "memory.retrieve": "retrieve",
            "memory.search": "search",
        },
        priority=14,
    )

    def __init__(self):
        self._workspace_path: Path = Path(".")
        self._files_dir: Path = Path(".")
        self._registry = None

    def configure(self, config: dict) -> None:
        """Get workspace path from config."""
        if "_workspace_path" in config:
            self._workspace_path = Path(config["_workspace_path"])
            self._files_dir = self._workspace_path / "memory" / "files"

    async def start(self) -> None:
        """Initialize files directory using workspace."""
        # Get workspace from registry
        if self._registry:
            try:
                workspace = self._registry.get("workspace")
                if workspace:
                    self._workspace_path = workspace.get_path()
                    self._files_dir = workspace.get_path("memory") / "files"
            except Exception:
                pass

        # Fallback to default workspace location
        if self._files_dir == Path("."):
            self._files_dir = Path.home() / ".cobot" / "workspace" / "memory" / "files"

        # Ensure directory exists
        self._files_dir.mkdir(parents=True, exist_ok=True)
        self.log_info(f"{self._files_dir}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def store(self, key: str, content: str) -> None:
        """Store content as a .md file.

        Args:
            key: Filename (without extension)
            content: Content to store
        """
        filepath = self._files_dir / f"{key}.md"
        filepath.write_text(content)

    def retrieve(self, key: str) -> str:
        """Retrieve content from a .md file.

        Args:
            key: Filename (without extension)

        Returns:
            Content or empty string if not found
        """
        filepath = self._files_dir / f"{key}.md"
        if filepath.exists():
            return filepath.read_text()
        return ""

    def search(self, query: str) -> list[dict]:
        """Search file contents for query.

        Simple keyword search - looks for query in file contents.

        Args:
            query: Search string

        Returns:
            List of matches: [{"key": "filename", "content": "...", "score": 1.0}]
        """
        results = []
        query_lower = query.lower()

        for filepath in self._files_dir.glob("*.md"):
            try:
                content = filepath.read_text()
                if query_lower in content.lower():
                    # Simple scoring: count occurrences
                    occurrences = content.lower().count(query_lower)
                    results.append(
                        {
                            "key": filepath.stem,
                            "content": content[:500],  # Truncate for preview
                            "score": min(1.0, occurrences / 10),  # Normalize score
                        }
                    )
            except Exception:
                pass

        return results

    def list_keys(self) -> list[str]:
        """List all stored memory keys.

        Returns:
            List of keys (filenames without .md)
        """
        return [f.stem for f in self._files_dir.glob("*.md")]


def create_plugin() -> MemoryFilesPlugin:
    """Factory function for plugin discovery."""
    return MemoryFilesPlugin()
