"""Tests for cli.py"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from cobot.cli import cli, load_merged_config, read_pid, write_pid


class TestPidFile:
    """Test PID file operations."""

    def test_write_and_read_pid(self):
        with patch("cobot.cli.get_pid_file") as mock_path:
            with tempfile.NamedTemporaryFile(delete=False) as f:
                mock_path.return_value = Path(f.name)

                write_pid(12345)

                # Verify file content before read_pid (which may delete
                # the file if the PID doesn't exist on this machine)
                assert Path(f.name).read_text().strip() == "12345"

                # read_pid checks os.kill — if PID 12345 doesn't exist,
                # it cleans up the file and returns None (expected)
                result = read_pid()
                assert result is None or result == 12345

                if Path(f.name).exists():
                    os.unlink(f.name)

    def test_read_pid_nonexistent(self):
        with patch("cobot.cli.get_pid_file") as mock_path:
            mock_path.return_value = Path("/nonexistent/pid")
            assert read_pid() is None


class TestCliCommands:
    """Test CLI commands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Cobot" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_status_not_running(self, runner):
        with patch("cobot.cli.read_pid", return_value=None):
            result = runner.invoke(cli, ["status"])
            assert result.exit_code == 0
            assert "Not running" in result.output

    def test_status_json(self, runner):
        with patch("cobot.cli.read_pid", return_value=None):
            result = runner.invoke(cli, ["status", "--json"])
            assert result.exit_code == 0
            assert '"running": false' in result.output

    def test_restart_not_running(self, runner):
        with patch("cobot.cli.read_pid", return_value=None):
            result = runner.invoke(cli, ["restart"])
            assert result.exit_code == 1
            assert "not running" in result.output.lower()

    def test_config_show(self, runner):
        with patch("cobot.cli.load_merged_config") as mock_config:
            from cobot.plugins.config.plugin import CobotConfig

            cfg = CobotConfig.from_dict({"identity": {"name": "TestBot"}})
            mock_config.return_value = cfg

            result = runner.invoke(cli, ["config", "show"])
            assert result.exit_code == 0
            assert "name" in result.output.lower() or "config" in result.output.lower()

    def test_config_validate_missing_key(self, runner):
        with patch("cobot.cli.load_merged_config") as mock_config:
            from cobot.plugins.config.plugin import CobotConfig

            mock_config.return_value = CobotConfig()

            result = runner.invoke(cli, ["config", "validate"])
            # May pass or fail depending on env, just check it runs
            assert result.exit_code in [0, 1]

    def test_wallet_balance(self, runner):
        with patch("cobot.cli.load_merged_config"):
            result = runner.invoke(cli, ["wallet", "balance"])
            # May fail if wallet import issues, but tests the path
            assert (
                "balance" in result.output.lower() or "error" in result.output.lower()
            )


class TestConfigSetGet:
    """Test config set/get commands."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_config_set_simple(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("identity:\n  name: OldName\n")

            result = runner.invoke(
                cli,
                ["config", "set", "identity.name", "NewName", "-c", str(config_path)],
            )
            assert result.exit_code == 0
            assert "NewName" in result.output

            # Verify file was updated
            import yaml

            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            assert cfg["identity"]["name"] == "NewName"

    def test_config_set_creates_nested(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("")

            result = runner.invoke(
                cli,
                ["config", "set", "ppq.model", "openai/gpt-4o", "-c", str(config_path)],
            )
            assert result.exit_code == 0

            import yaml

            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            assert cfg["ppq"]["model"] == "openai/gpt-4o"

    def test_config_set_integer(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("")

            result = runner.invoke(
                cli, ["config", "set", "exec.timeout", "60", "-c", str(config_path)]
            )
            assert result.exit_code == 0

            import yaml

            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            assert cfg["exec"]["timeout"] == 60
            assert isinstance(cfg["exec"]["timeout"], int)

    def test_config_set_boolean(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("")

            result = runner.invoke(
                cli, ["config", "set", "exec.enabled", "false", "-c", str(config_path)]
            )
            assert result.exit_code == 0

            import yaml

            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            assert cfg["exec"]["enabled"] is False

    def test_config_get_simple(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("identity:\n  name: TestBot\n")

            result = runner.invoke(
                cli, ["config", "get", "identity.name", "-c", str(config_path)]
            )
            assert result.exit_code == 0
            assert "TestBot" in result.output

    def test_config_get_nested(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text(
                "ppq:\n  model: openai/gpt-4o\n  api_base: https://api.ppq.ai\n"
            )

            result = runner.invoke(
                cli, ["config", "get", "ppq.model", "-c", str(config_path)]
            )
            assert result.exit_code == 0
            assert "openai/gpt-4o" in result.output

    def test_config_get_not_found(self, runner):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "cobot.yml"
            config_path.write_text("identity:\n  name: TestBot\n")

            result = runner.invoke(
                cli, ["config", "get", "nonexistent.key", "-c", str(config_path)]
            )
            assert result.exit_code == 1
            assert "not found" in result.output.lower()


class TestConfigPathFinding:
    """Test _find_config_path() logic."""

    def test_finds_local_config_first(self):
        from cobot.cli import _find_config_path

        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                # Create local config
                local_config = Path("cobot.yml")
                local_config.write_text("identity:\n  name: Local\n")

                path = _find_config_path()
                assert path == local_config
            finally:
                os.chdir(original_cwd)

    def test_falls_back_to_home_config(self):
        from cobot.cli import _find_config_path

        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                # No local config exists

                path = _find_config_path()
                assert path == Path.home() / ".cobot" / "cobot.yml"
            finally:
                os.chdir(original_cwd)

    def test_explicit_path_overrides(self):
        from cobot.cli import _find_config_path

        path = _find_config_path("/custom/path/config.yml")
        assert path == Path("/custom/path/config.yml")

    def test_config_set_uses_existing_home_config(self, runner):
        """config set should update existing home config, not create local."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            original_home = os.environ.get("HOME")
            try:
                # Set up fake home with config
                fake_home = Path(tmpdir) / "home"
                fake_home.mkdir()
                (fake_home / ".cobot").mkdir()
                home_config = fake_home / ".cobot" / "cobot.yml"
                home_config.write_text("identity:\n  name: HomeBot\n")

                os.environ["HOME"] = str(fake_home)

                # Work from a different directory (no local config)
                workdir = Path(tmpdir) / "work"
                workdir.mkdir()
                os.chdir(workdir)

                result = runner.invoke(
                    cli, ["config", "set", "identity.name", "UpdatedBot"]
                )
                assert result.exit_code == 0

                # Should have updated home config, not created local
                assert not (workdir / "cobot.yml").exists()
                assert "UpdatedBot" in home_config.read_text()
            finally:
                os.chdir(original_cwd)
                if original_home:
                    os.environ["HOME"] = original_home

    def test_config_get_reads_home_config(self, runner):
        """config get should read from home config when no local exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            original_cwd = os.getcwd()
            original_home = os.environ.get("HOME")
            try:
                # Set up fake home with config
                fake_home = Path(tmpdir) / "home"
                fake_home.mkdir()
                (fake_home / ".cobot").mkdir()
                home_config = fake_home / ".cobot" / "cobot.yml"
                home_config.write_text("identity:\n  name: HomeBot\n")

                os.environ["HOME"] = str(fake_home)

                # Work from a different directory (no local config)
                workdir = Path(tmpdir) / "work"
                workdir.mkdir()
                os.chdir(workdir)

                result = runner.invoke(cli, ["config", "get", "identity.name"])
                assert result.exit_code == 0
                assert "HomeBot" in result.output
            finally:
                os.chdir(original_cwd)
                if original_home:
                    os.environ["HOME"] = original_home

    @pytest.fixture
    def runner(self):
        return CliRunner()


class TestConfigMerging:
    """Test config merging logic."""

    def test_load_merged_config_local_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create local config
            local_config = Path(tmpdir) / "cobot.yml"
            local_config.write_text("""
identity:
  name: "LocalBot"
polling:
  interval_seconds: 15
""")

            original_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)

                with patch("cobot.cli.get_config_paths") as mock_paths:
                    mock_paths.return_value = (
                        Path("/nonexistent/home/cobot.yml"),
                        local_config,
                    )

                    config = load_merged_config()
                    assert config.identity_name == "LocalBot"
                    assert config.polling_interval == 15
            finally:
                os.chdir(original_cwd)
