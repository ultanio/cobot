# Cobot — Development Guide

**Generated:** 2026-03-02

## Prerequisites

- Python 3.11 or higher
- pip or uv package manager
- Git

## Setup

```bash
# Clone the repository
git clone https://github.com/ultanio/cobot
cd cobot

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS

# Install with all dependencies (including dev)
pip install -e ".[all]"
# Or with uv:
uv pip install -e ".[all]"
```

## Configuration

```bash
# Copy example config
cp cobot.yml.example cobot.yml
cp SOUL.md.example SOUL.md

# Edit configuration
# Set LLM provider (ppq or ollama)
# Configure identity name
# Add trusted contacts (Nostr npubs)
# Set API keys via environment variables
```

Key environment variables:
- `PPQ_API_KEY` — API key for PPQ.ai LLM provider
- `TELEGRAM_BOT_TOKEN` — Telegram bot token (optional)
- `NOSTR_PRIVKEY` — Nostr private key for FileDrop signatures (optional)

## Running

```bash
# Start agent (foreground)
cobot start

# Start as daemon
cobot start --daemon

# Stop running agent
cobot stop

# Check status
cobot status

# Interactive chat
cobot chat

# Setup wizard
cobot setup
```

## Testing

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v --tb=short

# Run specific test file
pytest tests/test_cobot.py

# Run specific test
pytest tests/test_cobot.py::test_function_name
```

Test locations:
- `tests/test_cobot.py` — Core agent tests
- `tests/test_cli.py` — CLI tests
- `tests/test_plugins.py` — Plugin system tests
- `tests/test_cli_plugins.py` — CLI plugin integration
- `tests/e2e/test_e2e.sh` — End-to-end tests

## Linting

```bash
# Check code style
ruff check .

# Auto-fix
ruff check --fix .

# Format
ruff format .
```

## Creating a Plugin

1. Create directory: `cobot/plugins/myplugin/`
2. Create `__init__.py` and `plugin.py`
3. Implement the Plugin class:

```python
from cobot.plugins.base import Plugin, PluginMeta

class MyPlugin(Plugin):
    meta = PluginMeta(
        id="myplugin",
        version="1.0.0",
        capabilities=["my_capability"],
        dependencies=["config"],
        priority=50,
    )

    def configure(self, config: dict) -> None:
        self._config = config

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass
```

4. Register in `cobot/plugins/__init__.py`

## Build & Release

- Build system: setuptools (configured in `pyproject.toml`)
- CI: GitHub Actions on push/PR to main (Python 3.11, 3.12, 3.13)
- Release: Automated via `.github/workflows/release.yml`

## Project Conventions

- All plugin lifecycle methods are async
- Hooks return modified context dicts
- Config is YAML with `${ENV_VAR}` substitution
- Hot reload watches plugin directories for changes
- PID file at `~/.cobot/cobot.pid` for daemon management
