"""Integration tests for cobot init/workspace experience.

Covers:
- #165: Workspace template file creation
- #166: Graceful plugin discovery with missing deps
- #167: Wizard init doesn't silently overwrite config
- #170: Fresh install, missing workspace, wizard flows

These tests use a temporary HOME directory to simulate fresh installs
without affecting the real system.
"""

import os
import subprocess

import yaml


def run_cobot(*args, env=None, input_text=None, timeout=10):
    """Run cobot CLI from the repo source with a custom environment."""
    result = subprocess.run(
        ["python3", "-m", "cobot.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
        timeout=timeout,
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    )
    return result


def make_clean_env(tmp_home):
    """Create an environment with a clean HOME (simulates fresh install)."""
    env = os.environ.copy()
    env["HOME"] = str(tmp_home)
    # Ensure cobot doesn't pick up any existing config
    env.pop("COBOT_CONFIG", None)
    env.pop("COBOT_WORKSPACE", None)
    return env


# ============================================================
# Scenario 1: Fresh install — no ~/.cobot at all
# ============================================================


class TestFreshInstall:
    """Test behavior when no ~/.cobot directory exists."""

    def test_wizard_init_creates_config(self, tmp_path):
        """wizard init -y should create config in a fresh HOME."""
        env = make_clean_env(tmp_path)
        result = run_cobot("wizard", "init", "-y", "--home", env=env)

        config_path = tmp_path / ".cobot" / "cobot.yml"
        assert config_path.exists(), (
            f"Config not created. stdout: {result.stdout}, stderr: {result.stderr}"
        )

        config = yaml.safe_load(config_path.read_text())
        assert config is not None
        assert "provider" in config
        assert "identity" in config

    def test_wizard_init_config_is_valid_yaml(self, tmp_path):
        """Generated config should be valid and parseable YAML."""
        env = make_clean_env(tmp_path)
        run_cobot("wizard", "init", "-y", "--home", env=env)

        config_path = tmp_path / ".cobot" / "cobot.yml"
        config = yaml.safe_load(config_path.read_text())

        # Should have sensible defaults
        assert config["provider"] in ("ppq", "ollama")
        assert config["identity"]["name"] == "MyAgent"
        assert "exec" in config


# ============================================================
# Scenario 2: Workspace template creation
# ============================================================


class TestWorkspaceTemplates:
    """Test that workspace plugin creates template files."""

    def test_workspace_creates_templates_on_start(self, tmp_path):
        """Starting cobot should create workspace with template files."""
        from cobot.plugins.workspace.plugin import WorkspacePlugin

        plugin = WorkspacePlugin()
        plugin._workspace = tmp_path / "workspace"

        import asyncio

        asyncio.get_event_loop().run_until_complete(plugin.start())

        expected_files = [
            "AGENTS.md",
            "SOUL.md",
            "USER.md",
            "MEMORY.md",
            "BOOTSTRAP.md",
            "IDENTITY.md",
        ]
        for f in expected_files:
            filepath = tmp_path / "workspace" / f
            assert filepath.exists(), f"{f} not created"
            assert len(filepath.read_text()) > 10, f"{f} is empty"

    def test_workspace_creates_subdirectories(self, tmp_path):
        """Starting cobot should create workspace subdirectories."""
        from cobot.plugins.workspace.plugin import WorkspacePlugin

        plugin = WorkspacePlugin()
        plugin._workspace = tmp_path / "workspace"

        import asyncio

        asyncio.get_event_loop().run_until_complete(plugin.start())

        for subdir in ["memory", "skills", "plugins", "logs"]:
            assert (tmp_path / "workspace" / subdir).is_dir()

    def test_workspace_preserves_existing_files(self, tmp_path):
        """Existing files must NOT be overwritten."""
        from cobot.plugins.workspace.plugin import WorkspacePlugin

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        custom_content = "# My custom AGENTS.md\nDo not touch."
        (workspace / "AGENTS.md").write_text(custom_content)

        plugin = WorkspacePlugin()
        plugin._workspace = workspace

        import asyncio

        asyncio.get_event_loop().run_until_complete(plugin.start())

        assert (workspace / "AGENTS.md").read_text() == custom_content
        # But other templates should still be created
        assert (workspace / "SOUL.md").exists()


# ============================================================
# Scenario 3: Missing workspace recovery
# ============================================================


class TestWorkspaceRecovery:
    """Test that cobot recovers when workspace directory is missing."""

    def test_workspace_recreated_after_deletion(self, tmp_path):
        """If workspace dir is deleted, it should be recreated on start."""
        from cobot.plugins.workspace.plugin import WorkspacePlugin

        import asyncio

        workspace = tmp_path / "workspace"

        # First start — creates everything
        plugin = WorkspacePlugin()
        plugin._workspace = workspace
        asyncio.get_event_loop().run_until_complete(plugin.start())
        assert workspace.exists()

        # Simulate deletion
        import shutil

        shutil.rmtree(workspace)
        assert not workspace.exists()

        # Second start — should recreate
        plugin2 = WorkspacePlugin()
        plugin2._workspace = workspace
        asyncio.get_event_loop().run_until_complete(plugin2.start())

        assert workspace.exists()
        assert (workspace / "AGENTS.md").exists()
        assert (workspace / "memory").is_dir()


# ============================================================
# Scenario 4: Wizard doesn't silently overwrite (#167)
# ============================================================


class TestWizardOverwrite:
    """Test that wizard respects existing config."""

    def test_non_interactive_overwrites(self, tmp_path):
        """wizard init -y should overwrite existing config (intentional)."""
        env = make_clean_env(tmp_path)
        config_path = tmp_path / ".cobot" / "cobot.yml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("provider: ollama\nidentity:\n  name: OldAgent\n")

        run_cobot("wizard", "init", "-y", "--home", env=env)

        config = yaml.safe_load(config_path.read_text())
        # -y uses defaults, so provider resets to ppq
        assert config["provider"] == "ppq"
        assert config["identity"]["name"] == "MyAgent"

    def test_wizard_with_explicit_config_path(self, tmp_path):
        """wizard init -y -c <path> creates config at specified location."""
        env = make_clean_env(tmp_path)
        config_path = tmp_path / "custom.yml"

        result = run_cobot("wizard", "init", "-y", "-c", str(config_path), env=env)

        assert config_path.exists(), (
            f"Config not at custom path. stdout: {result.stdout}, stderr: {result.stderr}"
        )
        config = yaml.safe_load(config_path.read_text())
        assert config["provider"] in ("ppq", "ollama")


# ============================================================
# Scenario 5: Plugin discovery with missing deps (#166)
# ============================================================


class TestGracefulDiscovery:
    """Test that plugin discovery handles missing deps gracefully."""

    def test_no_traceback_in_output(self, tmp_path):
        """Starting cobot with missing deps should not show tracebacks."""
        env = make_clean_env(tmp_path)
        # Create minimal config
        config_path = tmp_path / "cobot.yml"
        config_path.write_text("provider: ppq\nidentity:\n  name: Test\n")

        # Run cobot with --help to trigger plugin discovery without starting
        result = run_cobot("wizard", "plugins", env=env)

        # Should not contain scary traceback lines
        combined = result.stdout + result.stderr
        assert "Traceback (most recent call last)" not in combined, (
            f"Found traceback in output:\n{combined}"
        )
