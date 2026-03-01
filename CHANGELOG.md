# Changelog

All notable changes to Cobot will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-03-01

### Added

#### Plugins
- **Trust context plugin** — marks messages as trusted/untrusted based on source, injects trust context into system prompt (#158, #159)
- **Web plugin** with extension point architecture (#80, #81)
- **Knowledge plugin** for local vector search (#32)
- **Scheduled execution** — subagent, cron, and heartbeat plugins (#42)
- **Workspace templates** — creates AGENTS.md, SOUL.md, USER.md, MEMORY.md, BOOTSTRAP.md, IDENTITY.md on first init (#165, #169)
- **Workspace location config** — `workspace.location` in cobot.yml with backward compat (#176, #177)

#### Plugin System
- Plugin `consumes` relationships for dependency tracking (#62, #66)
- `optional_dependencies` and `consumes` fields in PluginMeta (#60, #63)
- Wallet implements ToolProvider pattern (#61, #65)
- CLI extension point refactoring (#78)

#### CLI & UX
- Colored logs with consistent format (#83)
- Wizard update mode — prompts update/overwrite/cancel for existing config (#167, #169)
- Graceful plugin discovery — missing optional deps log info instead of scary tracebacks (#166, #169)

#### Infrastructure
- Automated Alpha deployment via Forgejo CI with SSH forced command (#118, #119, #125, #126, #171–#181)
- Deploy workspace context files to Alpha (#139, #141, #142)
- Alpha integration test suite via filedrop (#143, #146)
- Integration tests for init/workspace experience (#170, #172)
- Forgejo CI — test matrix, build, e2e (#163, #164)

#### Documentation
- Plugin Design Guide (#69, #71)
- AGENTS.md for AI agent contributors (#84)
- Release procedure definitions (#7)

### Fixed
- Filedrop reply routing — replies go to sender not self (#151, #153, #154, #155)
- Telegram pairing passthrough — unknown chats allowed through when pairing is active (#100)
- Plugin anti-pattern violations resolved (#79)
- Compaction — async summarization with configurable token budgets (#74)
- Tools plugin uses workspace path instead of cwd (#174, #175)
- Wizard init no longer silently overwrites existing config (#167, #169)
- Identity test + filedrop wake stdout leak (#160, #162)
- Deploy script uses user systemd and configurable paths (#178)
- Security fixes: CB-014, CB-015, CB-016 (#67)
- CLI `run_loop_sync()` → `run_sync()` (#97, #117)
- Telegram plugin `call_extension` API mismatch (#104, #111)

### Changed
- Agent loop extracted into plugin, unified hooks and extension points (#34)

### Testing
- Added tests for filedrop, wallet, cron, heartbeat, subagent, security, compaction, logger, loop, ollama plugins (#105–#116)
- CI smoke test to catch API mismatches (#103, #116)

## [0.1.0] - 2026-02-13

### Added

#### Core
- Plugin registry with dependency resolution
- Extension point system (plugins define hooks, others implement)
- Hook chain for lifecycle events
- Multi-path plugin loading (system, user, project)
- Hot reload plugin for auto-restart on changes

#### Plugins
- `config` - Configuration management with env var expansion
- `ppq` - PPQ.ai LLM provider
- `ollama` - Local Ollama model support
- `nostr` - Nostr DMs (NIP-04 encrypted)
- `filedrop` - File-based communication
- `filedrop-nostr` - Schnorr signatures for FileDrop
- `wallet` - Lightning wallet via npub.cash
- `tools` - Shell execution, file operations
- `security` - Prompt injection shield
- `persistence` - Conversation memory
- `compaction` - Context window management
- `logger` - Logging plugin

#### CLI
- `cobot run` - Start agent
- `cobot run --stdin` - Interactive mode
- `cobot wizard init` - Interactive setup wizard
- `cobot wizard plugins` - Plugin configuration
- `cobot plugins list/info/enable/disable` - Plugin management

#### Infrastructure
- GitHub Actions CI (lint + test)
- Docker support with multi-stage build
- PyPI package publishing on tag
