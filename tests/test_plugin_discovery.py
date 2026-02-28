"""Tests for plugin discovery — graceful handling of missing deps."""

from cobot.plugins import discover_plugins


def test_discover_skips_missing_optional_deps(tmp_path):
    """Plugin with missing import should be skipped, not crash."""
    plugin_dir = tmp_path / "bad_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(
        "from nonexistent_package import Foo\n"
        "from cobot.plugins.base import Plugin, PluginMeta\n"
        "class BadPlugin(Plugin):\n"
        "    meta = PluginMeta(id='bad', version='1.0.0')\n"
        "def create_plugin(): return BadPlugin()\n"
    )
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 0


def test_discover_loads_good_plugins(tmp_path):
    """Normal plugins should still load fine."""
    plugin_dir = tmp_path / "good_plugin"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.py").write_text(
        "from cobot.plugins.base import Plugin, PluginMeta\n"
        "class GoodPlugin(Plugin):\n"
        "    meta = PluginMeta(id='good', version='1.0.0')\n"
        "    def configure(self, config): pass\n"
        "    async def start(self): pass\n"
        "    async def stop(self): pass\n"
        "def create_plugin(): return GoodPlugin()\n"
    )
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].meta.id == "good"


def test_discover_mixed_good_and_bad(tmp_path):
    """Bad plugins don't prevent good plugins from loading."""
    bad_dir = tmp_path / "aaa_bad"
    bad_dir.mkdir()
    (bad_dir / "plugin.py").write_text(
        "import nonexistent_module\ndef create_plugin(): pass\n"
    )

    good_dir = tmp_path / "zzz_good"
    good_dir.mkdir()
    (good_dir / "plugin.py").write_text(
        "from cobot.plugins.base import Plugin, PluginMeta\n"
        "class GoodPlugin(Plugin):\n"
        "    meta = PluginMeta(id='good', version='1.0.0')\n"
        "    def configure(self, config): pass\n"
        "    async def start(self): pass\n"
        "    async def stop(self): pass\n"
        "def create_plugin(): return GoodPlugin()\n"
    )
    plugins = discover_plugins(tmp_path)
    assert len(plugins) == 1
    assert plugins[0].meta.id == "good"
