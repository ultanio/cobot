"""Smoke tests — catch API mismatches and import errors early.

These tests import every plugin module, verify create_plugin() works,
and check that key interfaces exist. They're designed to catch the
kind of bugs that broke Alpha for a week (#97) and crashed the
telegram poll loop (#104).
"""

import importlib
import inspect
from pathlib import Path

import pytest

from cobot.plugins.base import Plugin, PluginMeta


# All plugin module paths (auto-discovered)
PLUGINS_DIR = Path(__file__).parent.parent / "cobot" / "plugins"
PLUGIN_MODULES = sorted(
    d.name
    for d in PLUGINS_DIR.iterdir()
    if d.is_dir() and (d / "plugin.py").exists() and d.name != "__pycache__"
)

# Plugins that require optional dependencies to import
OPTIONAL_DEP_PLUGINS = {"nostr", "telegram"}


class TestPluginDiscovery:
    """Verify all plugin modules can be found."""

    def test_plugins_exist(self):
        """At least 20 plugins should exist."""
        assert len(PLUGIN_MODULES) >= 20, (
            f"Expected >=20 plugins, found {len(PLUGIN_MODULES)}: {PLUGIN_MODULES}"
        )

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_plugin_has_init(self, plugin_name):
        """Every plugin directory has __init__.py."""
        init = PLUGINS_DIR / plugin_name / "__init__.py"
        assert init.exists(), f"{plugin_name} missing __init__.py"


class TestPluginImport:
    """Verify all plugins can be imported (with graceful skip for optional deps)."""

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_import_plugin_module(self, plugin_name):
        """Each plugin module can be imported without error."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            importlib.import_module(module_path)
        except ImportError as e:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip(f"Optional dependency missing: {e}")
            else:
                raise AssertionError(
                    f"Plugin '{plugin_name}' failed to import: {e}"
                ) from e


class TestCreatePlugin:
    """Verify every plugin has a working create_plugin() factory."""

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_create_plugin_exists(self, plugin_name):
        """Each plugin module exports create_plugin()."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        assert hasattr(mod, "create_plugin"), (
            f"{plugin_name} missing create_plugin() factory"
        )
        assert callable(mod.create_plugin)

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_create_plugin_returns_plugin(self, plugin_name):
        """create_plugin() returns a Plugin subclass instance."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        plugin = mod.create_plugin()
        assert isinstance(plugin, Plugin), (
            f"{plugin_name}.create_plugin() returned {type(plugin)}, "
            f"expected Plugin subclass"
        )


class TestPluginMeta:
    """Verify every plugin has valid metadata."""

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_has_meta(self, plugin_name):
        """Each plugin has a meta attribute with required fields."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        plugin = mod.create_plugin()
        assert hasattr(plugin, "meta"), f"{plugin_name} missing meta"
        assert isinstance(plugin.meta, PluginMeta), (
            f"{plugin_name}.meta is {type(plugin.meta)}, expected PluginMeta"
        )

        meta = plugin.meta
        assert meta.id, f"{plugin_name} meta.id is empty"
        assert meta.version, f"{plugin_name} meta.version is empty"


class TestBasePluginInterface:
    """Verify plugins implement the required BasePlugin interface."""

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_has_configure(self, plugin_name):
        """Each plugin has configure() method."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        plugin = mod.create_plugin()
        assert hasattr(plugin, "configure"), f"{plugin_name} missing configure()"
        assert callable(plugin.configure)

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_has_start_stop(self, plugin_name):
        """Each plugin has async start() and stop() methods."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        plugin = mod.create_plugin()
        assert hasattr(plugin, "start"), f"{plugin_name} missing start()"
        assert hasattr(plugin, "stop"), f"{plugin_name} missing stop()"
        assert inspect.iscoroutinefunction(plugin.start), (
            f"{plugin_name}.start() must be async"
        )
        assert inspect.iscoroutinefunction(plugin.stop), (
            f"{plugin_name}.stop() must be async"
        )

    @pytest.mark.parametrize("plugin_name", PLUGIN_MODULES)
    def test_configure_accepts_empty_dict(self, plugin_name):
        """configure({}) must not crash."""
        module_path = f"cobot.plugins.{plugin_name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            if plugin_name in OPTIONAL_DEP_PLUGINS:
                pytest.skip("Optional dependency missing")
            raise

        plugin = mod.create_plugin()
        # Should not raise
        plugin.configure({})


class TestCLIEntryPoint:
    """Verify CLI entry point resolves correctly (catches #97-style bugs)."""

    def test_cli_module_importable(self):
        """cobot.cli can be imported."""
        mod = importlib.import_module("cobot.cli")
        assert hasattr(mod, "main"), "cobot.cli missing main()"

    def test_agent_module_importable(self):
        """cobot.agent can be imported."""
        mod = importlib.import_module("cobot.agent")
        assert hasattr(mod, "Cobot"), "cobot.agent missing Cobot class"

    def test_cobot_has_run_sync(self):
        """Cobot class has run_sync() method (not run_loop_sync — see #97)."""
        from cobot.agent import Cobot

        assert hasattr(Cobot, "run_sync"), "Cobot missing run_sync()"
        assert not hasattr(Cobot, "run_loop_sync"), (
            "Cobot still has removed run_loop_sync() — see #97"
        )

    def test_cli_run_help(self):
        """'cobot run --help' works (exercises the CLI entry point)."""
        from click.testing import CliRunner
        from cobot.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0
        assert "stdin" in result.output

    def test_cli_run_invokes_run_sync(self):
        """'cobot run' calls bot.run_sync(), not a stale method (#97)."""
        import ast

        cli_path = Path(__file__).parent.parent / "cobot" / "cli.py"
        tree = ast.parse(cli_path.read_text())

        # Find all method calls in the run() function
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    assert node.func.attr != "run_loop_sync", (
                        "cli.py still calls run_loop_sync() — "
                        "should be run_sync() (see #97)"
                    )
