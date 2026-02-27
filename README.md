<p align="center">
  <img src="docs/logo.svg" alt="Cobot Logo" width="360">
</p>

<p align="center">
  <strong>Minimal self-sovereign AI agent with Nostr identity and Lightning wallet</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#plugins">Plugins</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#contributing">Contributing</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
  <img src="https://img.shields.io/badge/status-alpha-orange.svg" alt="Alpha">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/⚡-Lightning-yellow.svg" alt="Lightning">
  <img src="https://img.shields.io/badge/🔑-Nostr-purple.svg" alt="Nostr">
  <img src="https://img.shields.io/badge/🔌-Plugins-blue.svg" alt="Plugins">
</p>

---

## What is Cobot?

Cobot is a **lightweight personal AI agent** that runs on your hardware, identifies via Nostr, and transacts via Lightning Network. 

Unlike cloud-hosted assistants or complex frameworks, Cobot gives you true ownership:

> *Your keys, your identity, your agent.*

```
┌─────────────────────────────────────┐
│           Your Hardware             │  ← Physical control
├─────────────────────────────────────┤
│          Cobot Runtime              │  ← Self-hosted (~2K lines)
├─────────────────────────────────────┤
│    Nostr Identity (npub/nsec)       │  ← Self-sovereign ID
├─────────────────────────────────────┤
│   Lightning Wallet (npub.cash)      │  ← Self-sovereign money
├─────────────────────────────────────┤
│      LLM (local or cloud)           │  ← Flexible inference
└─────────────────────────────────────┘
```

## Features

| Feature | Description |
|---------|-------------|
| 🪶 **Minimal** | ~2K lines of Python, no bloat |
| 🔌 **Plugin Architecture** | Extensible via plugins with extension points |
| ⚡ **Lightning Wallet** | Send and receive sats autonomously |
| 🔑 **Nostr Identity** | Cryptographic identity via npub/nsec |
| 🔥 **Hot Reload** | Auto-restart on plugin changes |
| 🤖 **Multi-LLM** | PPQ, Ollama, OpenRouter, and more |
| 📁 **FileDrop** | File-based communication with Schnorr signatures |
| 🧩 **Extension Points** | Plugins can define hooks for others to implement |

## Quick Start

### Install

```bash
git clone https://github.com/ultanio/cobot
cd cobot

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows

# Install cobot
pip install -e .
```

### Setup Wizard

The easiest way to configure Cobot is the interactive wizard:

```bash
cobot wizard init
```

The wizard will guide you through:
- **Identity** — Name your agent
- **Provider** — Choose your LLM (PPQ, Ollama, etc.)
- **Plugins** — Configure any installed plugins

This creates a `cobot.yml` in your current directory.

### Run

```bash
# Start agent
cobot run

# Interactive mode
cobot run --stdin

# Check status
cobot status
```

### Manual Configuration

If you prefer manual setup, copy and edit the example config:

```bash
cp cobot.yml.example cobot.yml
# Edit cobot.yml with your settings
```

## Configuration

```yaml
# cobot.yml
provider: ppq  # or: ollama

identity:
  name: "MyAgent"

ppq:
  api_key: "${PPQ_API_KEY}"
  model: "gpt-4o"

# Optional: Nostr identity
nostr:
  relays:
    - "wss://relay.damus.io"

# Optional: Lightning wallet
wallet:
  provider: "npub.cash"

# Tool execution
exec:
  enabled: true
  timeout: 30
```

## Plugins

Cobot uses a **plugin architecture** where functionality is modular and extensible.

### Built-in Plugins

| Plugin | Capability | Description |
|--------|------------|-------------|
| `config` | — | Configuration management |
| `ppq` | `llm` | PPQ.ai LLM provider |
| `ollama` | `llm` | Local Ollama models |
| `nostr` | `communication` | Nostr DMs (NIP-04) |
| `filedrop` | `communication` | File-based messaging |
| `wallet` | `wallet` | Lightning via npub.cash |
| `tools` | `tools` | Shell, file operations |
| `hotreload` | — | Auto-restart on changes |
| `security` | — | Prompt injection shield |

### Extension Points

Cobot's **unique** feature: plugins can define extension points that other plugins implement.

```
┌─────────────┐                    ┌─────────────────┐
│   filedrop  │ ──defines──────►   │ Extension Point │
│   plugin    │                    │ filedrop.verify │
└─────────────┘                    └────────┬────────┘
                                            │
                                   implements
                                            │
                                   ┌────────▼────────┐
                                   │ filedrop-nostr  │
                                   │     plugin      │
                                   └─────────────────┘
```

Example:

```python
# filedrop defines extension point
meta = PluginMeta(
    id="filedrop",
    extension_points=["filedrop.before_write", "filedrop.after_read"],
)

# filedrop-nostr implements it
meta = PluginMeta(
    id="filedrop-nostr",
    implements={
        "filedrop.before_write": "sign_message",
        "filedrop.after_read": "verify_message",
    },
)
```

### Adding Plugins

Place plugins in one of these directories:

1. **System:** `/opt/cobot/plugins/`
2. **User:** `~/.cobot/plugins/`
3. **Project:** `./plugins/`

Each plugin needs a `plugin.py` with a `create_plugin()` factory function.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PLUGIN REGISTRY                           │
│  Registration │ Dependency resolution │ Extension points    │
├─────────────────────────────────────────────────────────────┤
│                      PLUGINS                                 │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐           │
│  │ config  │ │   llm   │ │  comms  │ │ wallet  │  ...      │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘           │
├─────────────────────────────────────────────────────────────┤
│                  EXTENSION POINTS                            │
│         Plugins define hooks → Others implement              │
├─────────────────────────────────────────────────────────────┤
│                   HOOK CHAIN                                 │
│  on_message → transform → llm_call → tool_exec → response  │
├─────────────────────────────────────────────────────────────┤
│                   CORE AGENT                                 │
│            Message loop │ Tool execution                     │
└─────────────────────────────────────────────────────────────┘
```

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Registry** | Central plugin management, dependency resolution |
| **Capability** | What a plugin provides: `llm`, `communication`, `wallet` |
| **Extension Point** | Hook that plugins can define for others to implement |
| **Hook Chain** | Lifecycle events that plugins can intercept |

## CLI Reference

```bash
# Core
cobot run              # Start the agent
cobot run --stdin      # Interactive mode (no Nostr)
cobot status           # Show status
cobot restart          # Restart running agent

# Setup
cobot wizard init      # Interactive setup wizard
cobot wizard plugins   # List plugins with wizard sections

# Configuration
cobot config show      # Show current configuration
cobot config validate  # Validate configuration
cobot config edit      # Edit config in $EDITOR
```

## Why Cobot?

| Feature | Cobot | OpenClaw | Others |
|---------|-------|----------|--------|
| **Lines of code** | ~2K | 430K+ | Varies |
| **Self-sovereign** | ✅ | ⚠️ | ❌ Cloud |
| **Nostr identity** | ✅ Native | ❌ | ❌ |
| **Lightning wallet** | ✅ Native | ❌ | ❌ |
| **Extension points** | ✅ Unique | ❌ | ❌ |
| **Hot reload** | ✅ | ❌ | ❌ |
| **Plugin system** | ✅ | ✅ Skills | Varies |

## Development

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check cobot/

# Format
ruff format cobot/
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Quick Links

- 🐛 [Report a bug](.github/ISSUE_TEMPLATE/bug_report.yml)
- ✨ [Request a feature](.github/ISSUE_TEMPLATE/feature_request.yml)
- 🔌 [Request a plugin](.github/ISSUE_TEMPLATE/plugin_request.yml)

## Roadmap

- [ ] Container isolation for tool execution
- [ ] Smart LLM routing (cost optimization)
- [ ] More messaging channels (Telegram, Discord)
- [ ] Agent-to-agent protocol
- [ ] Nostr relay for agent discovery

## License

MIT License — see [LICENSE](LICENSE) for details.

## Links

- [Nostr](https://nostr.com) — Decentralized social protocol
- [Lightning](https://lightning.network) — Bitcoin payment layer
- [npub.cash](https://npub.cash) — Lightning wallet for Nostr

---

<p align="center">
  <sub>Built with ⚡ by agents, for agents</sub>
</p>
# CI deploy test Fri Feb 27 10:16:35 UTC 2026
