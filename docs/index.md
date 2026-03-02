# Cobot — Documentation Index

**Generated:** 2026-03-02 | **Scan:** Deep | **Workflow:** document-project v1.2.0

## Project Overview

- **Type:** Monolith — Python CLI Agent
- **Primary Language:** Python 3.11+
- **Architecture:** Plugin Registry + Async Hook Pipeline
- **LOC:** ~6,154
- **Status:** Alpha

## Quick Reference

- **Tech Stack:** Python, Click, httpx, PyYAML, asyncio
- **Entry Point:** `cobot.cli:main` → `cobot.agent:Cobot`
- **Architecture Pattern:** Plugin-based with capability interfaces and hook pipeline
- **Plugins:** 20 built-in (LLM, communication, wallet, tools, memory, session, etc.)

## Generated Documentation

- [Project Overview](./project-overview.md) — Executive summary, tech stack, plugin ecosystem
- [Architecture](./architecture.md) — Core components, hook pipeline, design decisions
- [Source Tree Analysis](./source-tree-analysis.md) — Annotated directory tree with all plugins
- [Development Guide](./development-guide.md) — Setup, testing, plugin creation, conventions

## Existing Documentation

- [README](../README.md) — Project introduction and quick start
- [Architecture (original)](./architecture.md) — Existing architecture notes
- [Architecture: Multi-Agent Plan](./architecture/multiagent-plan.md) — Multi-agent design
- [Architecture: Session Plugin](./architecture/session-plugin.md) — Session plugin design
- [Quick Start Guide](./quickstart.md) — Getting started
- [For Agents Guide](./for-agents.md) — Guide for AI agents interacting with Cobot
- [Release Plan](./RELEASE-PLAN.md) — Release roadmap
- [Contributing](../CONTRIBUTING.md) — Contribution guidelines
- [Code of Conduct](../CODE_OF_CONDUCT.md) — Community standards
- [Security Policy](../SECURITY.md) — Security reporting
- [Changelog](../CHANGELOG.md) — Version history
- [Plugin README](../cobot/plugins/README.md) — Plugin development reference

## Getting Started

```bash
git clone https://github.com/ultanio/cobot && cd cobot
python -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
cp cobot.yml.example cobot.yml
# Edit cobot.yml with your LLM provider and identity
cobot start
```

For detailed setup: see [Development Guide](./development-guide.md)
For AI agents: see [For Agents Guide](./for-agents.md)


# Document Project — Workflow Complete

All documentation files have been written directly to `/home/doxios/cobot/main/docs/`.
