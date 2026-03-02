# Cobot — Source Tree Analysis

**Generated:** 2026-03-02

```
cobot/                          # Main package (Python)
├── __init__.py                 # Package init, exports run(), LLMProvider, etc.
├── agent.py                    # Core Cobot class — message loop, hook pipeline (~400 LOC)
├── cli.py                      # Click CLI — start, stop, chat, setup wizard (~900 LOC)
└── plugins/                    # Plugin system
    ├── __init__.py             # Plugin re-exports
    ├── base.py                 # Plugin ABC, PluginMeta, HOOK_METHODS (~240 LOC)
    ├── registry.py             # PluginRegistry singleton (~333 LOC)
    ├── interfaces.py           # Capability interfaces: LLM, Comm, Wallet, Tools (~234 LOC)
    ├── README.md               # Plugin development guide
    ├── communication/          # Channel-based message routing
    │   └── plugin.py           # OutgoingMessage, channel dispatch (~205 LOC)
    ├── compaction/             # Context window compaction
    │   └── plugin.py           # Summarize old messages to fit context (~153 LOC)
    ├── config/                 # Configuration management
    │   └── plugin.py           # YAML loading, env var expansion (~192 LOC)
    ├── context/                # Context enrichment for system prompt
    │   └── plugin.py           # Inject date, identity, etc. (~103 LOC)
    ├── filedrop/               # File-based inter-agent communication
    │   └── plugin.py           # Schnorr-signed file exchange (~180 LOC)
    ├── logger/                 # Logging infrastructure
    │   └── plugin.py           # Structured logging (~134 LOC)
    ├── memory/                 # Conversation memory
    │   └── plugin.py           # In-memory conversation tracking (~202 LOC)
    ├── memory_files/           # File-based memory persistence
    │   └── plugin.py           # Persist memory to disk (~131 LOC)
    ├── nostr/                  # Nostr protocol communication
    │   └── plugin.py           # Relay connections, DM handling (~222 LOC)
    ├── ollama/                 # Local Ollama LLM provider
    │   └── plugin.py           # Ollama API client (~196 LOC)
    ├── pairing/                # Agent pairing/trust
    │   ├── plugin.py           # Trust establishment, peer management (~303 LOC)
    │   └── storage.py          # Pairing data persistence
    ├── persistence/            # Data persistence layer
    │   └── plugin.py           # Generic data storage (~162 LOC)
    ├── ppq/                    # PPQ.ai LLM provider
    │   └── plugin.py           # PPQ API client (~131 LOC)
    ├── security/               # Security policies
    │   └── plugin.py           # Command filtering, access control (~98 LOC)
    ├── session/                # Multi-session management
    │   └── plugin.py           # Session lifecycle, isolation (~254 LOC)
    ├── soul/                   # System prompt management
    │   └── plugin.py           # SOUL.md loading/injection (~72 LOC)
    ├── telegram/               # Telegram bot integration
    │   └── plugin.py           # Bot handlers, group logging (~724 LOC)
    ├── tools/                  # Tool execution for LLM
    │   └── plugin.py           # Shell exec, tool definitions (~373 LOC)
    ├── wallet/                 # Lightning wallet
    │   └── plugin.py           # npub.cash integration (~125 LOC)
    └── workspace/              # Workspace management
        └── plugin.py           # Working directory management (~91 LOC)

tests/                          # Test suite
├── __init__.py
├── test_cobot.py               # Core agent tests
├── test_cli.py                 # CLI command tests
├── test_plugins.py             # Plugin system tests
├── test_cli_plugins.py         # CLI plugin integration tests
└── e2e/
    └── test_e2e.sh             # End-to-end test script

docs/                           # Documentation
├── architecture.md             # Architecture overview
├── architecture/               # Detailed architecture docs
│   ├── multiagent-plan.md      # Multi-agent architecture plan
│   └── session-plugin.md       # Session plugin design
├── quickstart.md               # Quick start guide
├── for-agents.md               # Guide for AI agents using Cobot
├── RELEASE-PLAN.md             # Release planning
└── logo.svg                    # Project logo

.github/                        # GitHub config
├── workflows/
│   ├── ci.yml                  # CI: pytest on Python 3.11-3.13
│   ├── e2e.yml                 # End-to-end tests
│   ├── release.yml             # Release automation
│   └── pages.yml               # GitHub Pages deployment
└── ISSUE_TEMPLATE/
    ├── bug_report.yml
    ├── feature_request.yml
    └── plugin_request.yml

# Root files
├── pyproject.toml              # Project metadata, dependencies, build config
├── cobot.yml.example           # Example configuration
├── SOUL.md.example             # Example system prompt
├── README.md                   # Project readme
├── CONTRIBUTING.md             # Contribution guidelines
├── CHANGELOG.md                # Change log
├── CODE_OF_CONDUCT.md          # Code of conduct
├── SECURITY.md                 # Security policy
├── LICENSE                     # MIT License
└── .gitignore
```

## Critical Directories

| Directory | Purpose | Key Files |
|-----------|---------|-----------|
| `cobot/` | Main package | agent.py, cli.py |
| `cobot/plugins/` | Plugin system core | base.py, registry.py, interfaces.py |
| `cobot/plugins/*/` | Individual plugins | plugin.py in each |
| `tests/` | Test suite | test_*.py files |
| `.github/workflows/` | CI/CD pipelines | ci.yml, release.yml |
| `docs/` | Documentation | architecture.md, quickstart.md |

## Entry Points

- **CLI:** `cobot.cli:main` (registered in pyproject.toml `[project.scripts]`)
- **Agent:** `cobot.agent:Cobot` class
- **Plugin Discovery:** `cobot/plugins/__init__.py` imports and registers all built-in plugins
