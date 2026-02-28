"""Tests for tools plugin."""

import os
import tempfile
from pathlib import Path


from ..plugin import ToolsPlugin, TOOL_DEFINITIONS, create_plugin


class TestToolDefinitions:
    """Test tool definitions are valid."""

    def test_all_tools_have_definitions(self):
        tool_names = [d["function"]["name"] for d in TOOL_DEFINITIONS]

        # Tools plugin provides shell/file tools only
        # Wallet tools are now in wallet plugin (ToolProvider)
        expected = [
            "read_file",
            "write_file",
            "edit_file",
            "exec",
            "restart_self",
        ]
        for name in expected:
            assert name in tool_names, f"Missing tool: {name}"

    def test_definitions_have_required_fields(self):
        for defn in TOOL_DEFINITIONS:
            assert defn["type"] == "function"
            assert "function" in defn
            assert "name" in defn["function"]
            assert "description" in defn["function"]
            assert "parameters" in defn["function"]


class TestToolsPlugin:
    """Test ToolsPlugin class."""

    def test_create_plugin(self):
        plugin = create_plugin()
        assert isinstance(plugin, ToolsPlugin)

    def test_plugin_meta(self):
        plugin = create_plugin()
        assert plugin.meta.id == "tools"
        assert "tools" in plugin.meta.capabilities

    def test_get_definitions(self):
        plugin = create_plugin()
        definitions = plugin.get_definitions()
        assert len(definitions) > 0
        assert all(d["type"] == "function" for d in definitions)


class TestToolsPluginConfig:
    """Test ToolsPlugin configuration."""

    def test_configure_exec_settings(self):
        plugin = create_plugin()
        plugin.configure(
            {
                "exec": {
                    "enabled": False,
                    "blocklist": ["rm -rf", "sudo"],
                    "timeout": 10,
                }
            }
        )

        assert plugin._exec_enabled is False
        assert "rm -rf" in plugin._exec_blocklist
        assert plugin._exec_timeout == 10

    def test_default_exec_enabled(self):
        plugin = create_plugin()
        plugin.configure({"exec": {}})
        assert plugin._exec_enabled is True

    def test_configure_workspace_path(self):
        plugin = create_plugin()
        plugin.configure({"_workspace_path": "/tmp/test-workspace"})
        assert plugin._base_dir == Path("/tmp/test-workspace")


class TestToolsPluginReadFile:
    """Test read_file tool."""

    def test_read_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("hello world")
            f.flush()

            try:
                plugin = create_plugin()
                plugin.configure({})
                result = plugin.execute("read_file", {"path": f.name})
                assert result == "hello world"
            finally:
                os.unlink(f.name)

    def test_read_nonexistent_file(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("read_file", {"path": "/nonexistent/file.txt"})
        assert "Error" in result
        assert "not found" in result.lower()

    def test_read_file_truncation(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("x" * 100000)  # 100KB
            f.flush()

            try:
                plugin = create_plugin()
                plugin.configure({})
                plugin._context_budget = 1000  # Small budget for test
                result = plugin.execute("read_file", {"path": f.name})
                assert "[truncated" in result
                assert len(result) < 2000
            finally:
                os.unlink(f.name)


class TestToolsPluginWriteFile:
    """Test write_file tool."""

    def test_write_new_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "new.txt"

            plugin = create_plugin()
            plugin.configure({})
            result = plugin.execute(
                "write_file", {"path": str(path), "content": "hello"}
            )

            assert "Successfully" in result
            assert path.read_text() == "hello"

    def test_write_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "sub" / "dir" / "file.txt"

            plugin = create_plugin()
            plugin.configure({})
            plugin.execute("write_file", {"path": str(path), "content": "nested"})

            assert path.read_text() == "nested"

    def test_write_protected_file_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = create_plugin()
            plugin.configure({})
            plugin._base_dir = Path(tmpdir)

            # Create a path that matches protected pattern
            protected_dir = Path(tmpdir) / "cobot" / "plugins" / "base.py"
            protected_dir.parent.mkdir(parents=True, exist_ok=True)

            result = plugin.execute(
                "write_file", {"path": str(protected_dir), "content": "hack"}
            )

            assert "Error" in result
            assert "Protected" in result


class TestToolsPluginEditFile:
    """Test edit_file tool."""

    def test_edit_replaces_text(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello world")
            f.flush()

            try:
                plugin = create_plugin()
                plugin.configure({})
                result = plugin.execute(
                    "edit_file",
                    {"path": f.name, "old_text": "world", "new_text": "universe"},
                )

                assert "Successfully" in result
                assert Path(f.name).read_text() == "hello universe"
            finally:
                os.unlink(f.name)

    def test_edit_text_not_found(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write("hello world")
            f.flush()

            try:
                plugin = create_plugin()
                plugin.configure({})
                result = plugin.execute(
                    "edit_file",
                    {
                        "path": f.name,
                        "old_text": "nonexistent",
                        "new_text": "replacement",
                    },
                )

                assert "Error" in result
                assert "not found" in result.lower()
            finally:
                os.unlink(f.name)


class TestToolsPluginExec:
    """Test exec tool."""

    def test_exec_simple_command(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("exec", {"command": "echo hello"})
        assert "hello" in result

    def test_exec_captures_stderr(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("exec", {"command": "echo error >&2"})
        assert "error" in result
        assert "stderr" in result.lower()

    def test_exec_returns_exit_code(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("exec", {"command": "exit 42"})
        assert "exit code: 42" in result.lower()

    def test_exec_blocked_command(self):
        plugin = create_plugin()
        plugin.configure({"exec": {"blocklist": ["dangerous"]}})

        result = plugin.execute("exec", {"command": "run dangerous thing"})
        assert "Error" in result or "blocked" in result.lower()

    def test_exec_disabled(self):
        plugin = create_plugin()
        plugin.configure({"exec": {"enabled": False}})

        result = plugin.execute("exec", {"command": "echo hello"})
        assert "Error" in result or "disabled" in result.lower()

    def test_exec_timeout(self):
        plugin = create_plugin()
        plugin.configure({"exec": {"timeout": 1}})

        result = plugin.execute("exec", {"command": "sleep 10"})
        assert "Error" in result
        assert "timed out" in result.lower()

    def test_exec_runs_in_workspace_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin = create_plugin()
            plugin.configure({"_workspace_path": tmpdir})
            result = plugin.execute("exec", {"command": "pwd"})
            assert tmpdir in result


class TestToolsPluginRestart:
    """Test restart_self tool."""

    def test_restart_sets_flag(self):
        plugin = create_plugin()
        plugin.configure({})
        assert plugin.restart_requested is False

        result = plugin.execute("restart_self", {})

        assert "Restart requested" in result
        assert plugin.restart_requested is True


class TestToolsPluginUnknownTool:
    """Test handling of unknown tools."""

    def test_unknown_tool_returns_error(self):
        plugin = create_plugin()
        plugin.configure({})
        result = plugin.execute("nonexistent_tool", {})
        assert "Error" in result
        assert "Unknown tool" in result
