"""Tests for workspace template file creation."""

import pytest
from unittest.mock import MagicMock

from ..plugin import WorkspacePlugin


@pytest.fixture
def plugin(tmp_path):
    """Create a workspace plugin with a temp directory."""
    p = WorkspacePlugin()
    p._registry = MagicMock()
    p._workspace = tmp_path / "workspace"
    return p


class TestTemplateCreation:
    @pytest.mark.asyncio
    async def test_creates_template_files(self, plugin):
        """Templates should be created on first start."""
        await plugin.start()
        for filename in WorkspacePlugin.TEMPLATES:
            assert (plugin._workspace / filename).exists()

    @pytest.mark.asyncio
    async def test_does_not_overwrite_existing(self, plugin):
        """Existing files should not be overwritten."""
        plugin._workspace.mkdir(parents=True)
        custom = "My custom AGENTS.md"
        (plugin._workspace / "AGENTS.md").write_text(custom)
        await plugin.start()
        assert (plugin._workspace / "AGENTS.md").read_text() == custom

    @pytest.mark.asyncio
    async def test_creates_subdirectories(self, plugin):
        """Standard subdirectories should be created."""
        await plugin.start()
        for subdir in ["memory", "skills", "plugins", "logs"]:
            assert (plugin._workspace / subdir).is_dir()

    @pytest.mark.asyncio
    async def test_templates_have_content(self, plugin):
        """Template files should not be empty."""
        await plugin.start()
        for filename in WorkspacePlugin.TEMPLATES:
            content = (plugin._workspace / filename).read_text()
            assert len(content) > 10
