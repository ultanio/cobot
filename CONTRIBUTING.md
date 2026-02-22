# Contributing to Cobot

Thanks for your interest in contributing! 🎉

## Quick Start

```bash
# Clone
git clone https://github.com/ultanio/cobot
cd cobot

# Setup
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Test
pytest
```

## Ways to Contribute

### 🐛 Report Bugs
- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml)
- Include logs, config (sanitized), and reproduction steps

### ✨ Suggest Features
- Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml)
- Explain the problem you're solving

### 🔌 Create Plugins
The best way to extend Cobot is via plugins. See [Plugin Development](#plugin-development).

### 📝 Improve Docs
- Fix typos, clarify explanations
- Add examples and tutorials
- Translate documentation

### 🧪 Write Tests
- Increase test coverage
- Add integration tests
- Test edge cases

## Plugin Development

> **📐 For design principles, patterns catalog, and anti-patterns, see the [Plugin Design Guide](docs/plugin-design-guide.md).**

Plugins are the preferred way to add functionality. Don't modify core unless necessary.

### Creating a Plugin

1. Create directory: `plugins/myplugin/`
2. Add `__init__.py` and `plugin.py`
3. Implement the plugin class:

```python
# plugins/myplugin/plugin.py
from cobot.plugins.base import Plugin, PluginMeta

class MyPlugin(Plugin):
    meta = PluginMeta(
        id="myplugin",
        version="1.0.0",
        capabilities=["mycap"],
        dependencies=[],
        priority=50,
    )
    
    def configure(self, config: dict) -> None:
        self._config = config.get("myplugin", {})
    
    def start(self) -> None:
        print("[MyPlugin] Started")
    
    def stop(self) -> None:
        pass

def create_plugin() -> MyPlugin:
    return MyPlugin()
```

### Extension Points

Plugins can define extension points for others to implement:

```python
# Plugin A defines an extension point
meta = PluginMeta(
    id="pluginA",
    extension_points=["pluginA.before_action", "pluginA.after_action"],
)

# Call it in your plugin
ctx = self.call_extension("pluginA.before_action", {"data": value})
if ctx.get("abort"):
    return
```

```python
# Plugin B implements it
meta = PluginMeta(
    id="pluginB",
    implements={"pluginA.before_action": "my_handler"},
)

def my_handler(self, ctx: dict) -> dict:
    # Process context
    return ctx
```

### Testing Plugins

```python
# tests/test_myplugin.py
from cobot.plugins.registry import PluginRegistry
from plugins.myplugin.plugin import create_plugin

def test_myplugin():
    registry = PluginRegistry()
    plugin = create_plugin()
    registry.register(type(plugin))
    
    # Test plugin behavior
    assert registry.get("myplugin") is not None
```

## Code Style

We use [ruff](https://github.com/astral-sh/ruff) for linting and formatting:

```bash
# Lint
ruff check cobot/

# Format
ruff format cobot/

# Fix auto-fixable issues
ruff check --fix cobot/
```

### Guidelines

- Keep it minimal — don't add complexity unless necessary
- Prefer composition over inheritance
- Write docstrings for public APIs
- Add type hints
- Keep plugins independent

## Pull Request Process

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run tests: `pytest`
5. Run linter: `ruff check cobot/`
6. Commit with clear message
7. Push and create PR

### PR Checklist

- [ ] Tests pass
- [ ] Linter passes
- [ ] Docs updated (if needed)
- [ ] CHANGELOG updated (for user-facing changes)
- [ ] Breaking changes noted

## Architecture Decisions

Before making significant changes, understand the design principles:

1. **Plugin-first** — Functionality goes in plugins, not core
2. **Extension points** — Plugins extend each other via hooks
3. **Minimal core** — Keep the agent loop simple
4. **Sovereignty** — No cloud dependencies in core
5. **Crypto-native** — Nostr/Lightning are first-class

## Questions?

- Open a [discussion](https://github.com/ultanio/cobot/discussions)
- Check existing [issues](https://github.com/ultanio/cobot/issues)

## License

By contributing, you agree that your contributions will be licensed under MIT.
