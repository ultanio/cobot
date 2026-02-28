"""Tests for workspace plugin."""

import asyncio
import os
import tempfile
from pathlib import Path


from .. import create_plugin


class TestWorkspacePlugin:
    """Tests for the workspace plugin."""

    def test_workspace_provides_paths(self):
        """Workspace plugin should provide path accessors."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.configure({"workspace": tmpdir})
            asyncio.run(plugin.start())

            # Should provide workspace root
            assert plugin.get_path() == Path(tmpdir)

            # Should provide subdirectory paths
            assert plugin.get_path("memory") == Path(tmpdir) / "memory"
            assert plugin.get_path("skills") == Path(tmpdir) / "skills"

    def test_workspace_creates_dirs_on_start(self):
        """Workspace should create subdirectories if missing."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace_dir = Path(tmpdir) / "workspace"
            plugin.configure({"workspace": str(workspace_dir)})
            asyncio.run(plugin.start())

            # Should create workspace and subdirs
            assert workspace_dir.exists()
            assert (workspace_dir / "memory").exists()
            assert (workspace_dir / "skills").exists()
            assert (workspace_dir / "plugins").exists()
            assert (workspace_dir / "logs").exists()

    def test_workspace_priority_cli_over_env(self):
        """CLI arg should win over env var."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            cli_path = Path(tmpdir) / "cli"
            env_path = Path(tmpdir) / "env"

            os.environ["COBOT_WORKSPACE"] = str(env_path)
            try:
                # _resolved_workspace simulates CLI resolution
                plugin.configure(
                    {
                        "workspace": str(env_path),
                        "_cli_workspace": str(cli_path),
                    }
                )
                asyncio.run(plugin.start())

                assert plugin.get_path() == cli_path
            finally:
                del os.environ["COBOT_WORKSPACE"]

    def test_workspace_priority_env_over_config(self):
        """Env var should win over config."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / "env"
            config_path = Path(tmpdir) / "config"

            os.environ["COBOT_WORKSPACE"] = str(env_path)
            try:
                plugin.configure({"workspace": str(config_path)})
                asyncio.run(plugin.start())

                assert plugin.get_path() == env_path
            finally:
                del os.environ["COBOT_WORKSPACE"]

    def test_workspace_default_location(self):
        """Should default to ~/.cobot/workspace."""
        plugin = create_plugin()
        plugin.configure({})

        expected = Path.home() / ".cobot" / "workspace"
        assert plugin.get_path() == expected

    def test_workspace_nested_config(self):
        """Should support workspace.location nested config."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.configure({"workspace": {"location": tmpdir}})
            asyncio.run(plugin.start())

            assert plugin.get_path() == Path(tmpdir)

    def test_workspace_flat_string_backward_compat(self):
        """Should still support flat string workspace config."""
        plugin = create_plugin()

        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.configure({"workspace": tmpdir})
            asyncio.run(plugin.start())

            assert plugin.get_path() == Path(tmpdir)
