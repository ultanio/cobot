# AGENTS.md — For AI Agents Working on Cobot

You're an AI agent about to work on this codebase. This file tells you what you need to know.

## What Is Cobot?

A minimal (~2K lines) self-sovereign AI agent framework in Python. Agents built with Cobot get:
- **Nostr identity** (npub/nsec) — cryptographic, decentralized
- **Lightning wallet** (npub.cash) — autonomous payments
- **Plugin architecture** — everything is a plugin, including LLM providers
- **Extension points** — plugins can define hooks that other plugins implement

## Repo Layout

```
cobot/
├── cobot/
│   ├── agent.py          # Core agent loop (~250 lines) — START HERE
│   ├── cli.py            # CLI commands (click-based)
│   └── plugins/
│       ├── base.py       # Plugin base class + PluginMeta
│       ├── registry.py   # Plugin registry (dependency resolution, hooks)
│       ├── interfaces.py # Capability interfaces (LLMProvider, ToolProvider, etc.)
│       └── <name>/       # Each plugin: plugin.py + README.md + tests/
├── tests/                # Top-level tests (CLI, integration)
├── docs/
│   ├── architecture.md   # Mermaid diagrams of plugin system
│   ├── for-agents.md     # Plugin development reference (READ THIS for hook details)
│   └── quickstart.md     # User-facing setup guide
├── cobot.yml.example     # Example configuration
├── SOUL.md.example       # Example system prompt
└── pyproject.toml        # Package config, dependencies, ruff settings
```

## Before You Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest --ignore=cobot/plugins/nostr/tests --ignore=cobot/plugins/telegram/tests
```

The nostr and telegram test suites need optional dependencies (`pynostr`, `python-telegram-bot`). Skip them unless you're working on those plugins. All other tests (200) should pass.

## Architecture in 60 Seconds

1. **Everything is a plugin.** LLM providers, communication channels, tools, security — all plugins.
2. **Plugins declare capabilities** (`llm`, `communication`, `wallet`, `tools`) and are looked up by capability, not name.
3. **Extension points** let plugins define hooks that other plugins implement. Example: `filedrop` defines `filedrop.before_write`, `filedrop-nostr` implements it to add Schnorr signatures.
4. **Hook chain** processes every message through lifecycle hooks: `on_message_received` → `transform_system_prompt` → `transform_history` → `on_before_llm_call` → LLM → `on_after_llm_call` → tool loop → `transform_response` → send.
5. **The core agent** (`agent.py`) is just a message loop that delegates everything to the registry.

Read `docs/for-agents.md` for the full plugin development reference.

## Current Priorities

### 🔴 Security (Issue #4)

The repo has a [security audit](https://github.com/ultanio/cobot/issues/4) with 21 findings. The core architectural issue:

> Untrusted input (Nostr/Telegram) → LLM → privileged OS operations, without sufficient gating.

**Critical fixes needed:**
- **CB-001:** `tools/plugin.py` — exec tool runs arbitrary shell commands with no sandboxing
- **CB-002:** `tools/plugin.py` — file read/write has no path restrictions
- **CB-003:** The prompt injection → RCE chain (architectural)
- **CB-004:** `wallet/plugin.py` — LLM can drain wallet via tool calls without human approval

**High priority:**
- **CB-005:** `security/plugin.py` — fails open (if detection errors, message passes through)
- **CB-006:** `nostr/plugin.py` — private key handling needs improvement
- **CB-007:** `filedrop/plugin.py` — world-writable directories
- **CB-008:** `tools/plugin.py` — subprocess inherits all env vars (leaks secrets)
- **CB-009:** `agent.py` — `os.execv` restart allows argument injection

See issue #4 for the full list (medium + low findings).

## What's Safe to Change

| Area | Risk | Notes |
|------|------|-------|
| Tests | ✅ Low | Add freely, never delete without reason |
| Plugin READMEs | ✅ Low | Improve docs anytime |
| New plugins | ✅ Low | Add in `cobot/plugins/<name>/` with tests |
| Bug fixes with tests | 🟡 Medium | Always add a regression test |
| `registry.py` / `base.py` | 🔴 High | Core infrastructure — test thoroughly |
| `agent.py` | 🔴 High | The main loop — be very careful |
| Hook chain changes | 🔴 High | Can break all plugins |

## Code Style

- **Formatter/linter:** `ruff` (config in `pyproject.toml`)
- **Type hints:** Yes, use them
- **Docstrings:** Required for public APIs
- **Tests:** Required for new functionality, pytest + pytest-asyncio
- **Async:** Core agent loop is async. Plugins can be sync (hooks are awaited via `run()`)

```bash
ruff check cobot/    # Lint
ruff format cobot/   # Format
pytest               # Test
```

## PR Checklist

Before opening a PR:
- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] `ruff check` and `ruff format` pass
- [ ] CHANGELOG.md updated (for user-facing changes)
- [ ] No secrets, keys, or tokens in code (use `${ENV_VAR}` in config)
- [ ] Breaking changes documented

## Don't

- Don't modify core (`agent.py`, `registry.py`) without understanding the hook chain
- Don't add cloud dependencies to core — sovereignty is the point
- Don't hardcode API keys or secrets
- Don't skip tests "because it's a small change"
- Don't add heavyweight dependencies for things Python stdlib can do
