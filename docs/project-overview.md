# Cobot — Project Overview

**Generated:** 2026-03-02 | **Scan Level:** Deep | **Type:** Python CLI Agent

## Executive Summary

Cobot is a **minimal self-sovereign AI agent** (~6K lines of Python) that runs on user hardware, identifies via Nostr keypairs, and transacts via Lightning Network. It features a robust plugin architecture where all functionality — LLM inference, communication, persistence, tools — is provided through discoverable, priority-ordered plugins with lifecycle hooks.

> *Your keys, your identity, your agent.*

## Quick Reference

| Attribute | Value |
|-----------|-------|
| **Language** | Python 3.11+ |
| **Framework** | Click (CLI), asyncio (runtime) |
| **Package Manager** | pip / uv (setuptools backend) |
| **Architecture** | Plugin-based agent with hook pipeline |
| **Entry Point** | `cobot.cli:main` (Click CLI) → `cobot.agent:Cobot` |
| **Repository Type** | Monolith |
| **LOC** | ~6,154 (core + plugins) |
| **License** | MIT |
| **Status** | Alpha |

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| Language | Python | ≥3.11 | Core runtime |
| CLI | Click | ≥8.0 | Command-line interface |
| HTTP | httpx | ≥0.27 | Async HTTP client for LLM APIs |
| Config | PyYAML | ≥6.0 | YAML configuration parsing |
| Telegram | python-telegram-bot | ≥21.0 | Telegram integration (optional) |
| Nostr | pynostr | ≥0.6 | Nostr protocol (optional) |
| Testing | pytest, pytest-asyncio | ≥8.0 | Unit/integration tests |
| Linting | ruff | ≥0.2 | Code formatting and linting |
| CI/CD | GitHub Actions | — | CI on Python 3.11/3.12/3.13 |

## Architecture Pattern

**Plugin Registry + Hook Pipeline**

The core agent (`Cobot`) is a thin orchestrator. All functionality is provided by plugins registered in a central `PluginRegistry`. Plugins declare capabilities (e.g., `"llm"`, `"communication"`, `"wallet"`) and implement standardized interfaces (`LLMProvider`, `CommunicationProvider`, etc.).

Message processing flows through an ordered hook pipeline:
```
on_message_received → transform_system_prompt → transform_history →
on_before_llm_call → [LLM] → on_after_llm_call →
on_before_tool_exec → [Tool] → on_after_tool_exec →
transform_response → on_before_send → [Send] → on_after_send
```

## Plugin Ecosystem (20 built-in plugins)

| Plugin | Capability | Purpose |
|--------|-----------|---------|
| config | — | YAML configuration loading |
| logger | — | Logging infrastructure |
| ppq | llm | PPQ.ai LLM provider |
| ollama | llm | Local Ollama LLM provider |
| communication | communication | Channel-based message routing |
| telegram | — | Telegram bot integration |
| nostr | communication | Nostr protocol messaging |
| wallet | wallet | Lightning wallet (npub.cash) |
| tools | tools | Tool execution for LLM |
| soul | — | System prompt (SOUL.md) management |
| context | — | Context enrichment |
| memory | — | Conversation memory |
| memory_files | — | File-based memory persistence |
| persistence | — | Data persistence layer |
| session | — | Multi-session management |
| compaction | — | Context window compaction |
| security | — | Security policies |
| filedrop | — | File-based inter-agent communication with Schnorr signatures |
| pairing | — | Agent pairing/trust management |
| workspace | — | Workspace/directory management |

## Repository Structure

```
cobot/                  # Main package
├── __init__.py
├── agent.py           # Core agent class (~400 LOC)
├── cli.py             # Click CLI commands (~900 LOC)
└── plugins/           # Plugin system
    ├── base.py        # Plugin ABC + PluginMeta
    ├── registry.py    # PluginRegistry (central management)
    ├── interfaces.py  # Capability interfaces (LLMProvider, etc.)
    └── <plugin>/      # 20 individual plugin directories
        ├── __init__.py
        └── plugin.py
tests/                 # Test suite
docs/                  # Documentation
.github/workflows/     # CI/CD (ci.yml, e2e.yml, release.yml, pages.yml)
```

## Links

- **GitHub:** https://github.com/ultanio/cobot
- **Docs Index:** [index.md](./index.md)
- **Architecture:** [architecture.md](./architecture.md)
- **Source Tree:** [source-tree-analysis.md](./source-tree-analysis.md)
- **Development Guide:** [development-guide.md](./development-guide.md)
