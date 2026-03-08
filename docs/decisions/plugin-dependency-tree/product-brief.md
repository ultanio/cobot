---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - /olymp/shared/files/prd-draft-plugin-dependency-tree.md
date: 2026-03-08
author: k9ert
---

# Product Brief: Cobot Plugin Dependency Tree Resolution

## Executive Summary

Cobot's plugin system currently loads plugins from a flat enabled/disabled list with no dependency-tree resolution. This means all enabled plugins load regardless of whether they're actually needed by the active entry points, leading to runtime crashes (e.g., Issue #227: headless mode crash when telegram plugins load without a loop driver), implicit contracts between plugins and the agent runtime, and phantom dependencies that are declared but never used for resolution.

This initiative introduces **dependency tree resolution from root entry points** — users declare which top-level plugins they need, and the system automatically resolves and loads only the required dependency chain. This transforms plugin loading from "load everything enabled" to "load what's needed," making Cobot configurations predictable, crash-free, and self-documenting.

---

## Core Vision

### Problem Statement

Cobot's plugin loading is a flat filter over an enabled/disabled list. The 30+ plugins declare `dependencies` in their metadata, but these are only validated post-registration — never used to determine *what should load*. There is no concept of a "root" or "entry point" plugin. Every enabled plugin loads equally, and the agent runtime (`agent.py`) implicitly requires certain capabilities (loop, LLM provider) that are never expressed in the dependency graph. The result: users must manually curate plugin lists, and misconfigurations only surface as runtime crashes.

### Problem Impact

- **Runtime crashes:** Enabling telegram + telegram_lurker without a loop plugin causes `agent.run_loop()` to crash (Issue #227). The plugins load fine — the failure is silent until execution.
- **Configuration fragility:** Users must understand internal plugin interdependencies to write valid configs. No guardrails exist.
- **Wasted resources:** All enabled plugins load, configure, and start — even those unreachable from any active entry point.
- **Maintenance burden:** As the plugin count grows (currently 30), the implicit dependency web becomes harder to reason about. PR #228 is a bandaid that handles edge cases in `agent.py` rather than fixing the structural gap.

### Why Existing Solutions Fall Short

- **Current `_check_dependencies()`** validates that declared dependencies are present *after* registration, but never drives what should load. It's a post-hoc safety net, not a resolution engine.
- **`_resolve_load_order()`** uses priority-based sorting with a TODO comment for topological sort — acknowledging the gap without addressing it.
- **PR #228 (headless fix)** makes `agent.py` tolerant of missing loop plugins. This is Option C from the PRD draft: keep flat loading, make everything optional. It papers over the symptom without fixing the architecture.
- **Manual plugin curation** works but doesn't scale and provides no feedback when configurations are incomplete or contradictory.

### Proposed Solution

Implement **load policy + transitive dependency resolution**:

1. **Load policy** determines the default: `policy: enable` (load everything, use `disabled` to exclude) or `policy: disable` (load nothing, use `enabled` to include)
2. The loader **resolves transitive dependencies** — if you enable plugin A and A depends on B, B is auto-loaded
3. **Conflict detection** — if a required dependency is explicitly disabled, the loader raises a hard error at startup (not a runtime crash)
4. Dependencies flow **downward only** — enabling B does not auto-enable A just because A depends on B
5. Capability-based dependencies (e.g., "I need an LLM provider") complement ID-based dependencies for flexibility

**Example configs:**

```yaml
# Full agent — everything loads, exclude what you don't want
plugins:
  policy: enable
  disabled: [ollama, nostr]
```

```yaml
# Minimal/headless — only what you ask for (+ their deps)
plugins:
  policy: disable
  enabled: [web]           # web's transitive deps auto-included
```

### Key Differentiators

- **Leverages existing metadata:** `PluginMeta` already declares `dependencies`, `capabilities`, `optional_dependencies`, and `consumes`. The data model is ready — it just needs a resolution engine.
- **Load policy covers both use cases:** Full agent (enable-by-default) and minimal/headless (disable-by-default) without separate config models.
- **Fail-fast at config time:** Conflicts (e.g., enabling telegram but disabling communication) surface during resolution, before any plugin starts — not as runtime crashes.
- **No new concepts:** `enabled`/`disabled` lists already exist. `policy` just flips the default. Dependency resolution is additive on top.

---

## Target Users

### Primary Users

**1. Cobot Instance Operators ("The Deployer")**

- **Profile:** Technical users who configure and deploy Cobot instances for specific purposes — archival bots, interactive agents, web dashboards, etc.
- **Current Pain:** Must manually maintain plugin lists, discovering dependencies through trial-and-error or reading source code. A misconfiguration only surfaces as a crash at startup or, worse, during runtime.
- **Goal:** Write a minimal config that declares *intent* (e.g., "I want a Telegram lurker bot") and trust the system to figure out the rest.
- **Success Moment:** Setting `policy: disable` + `enabled: [telegram_lurker]` and having exactly the right plugins load — no crashes, no surprises.

**2. Plugin Developers ("The Extender")**

- **Profile:** Developers building new Cobot plugins who need to declare dependencies correctly and understand the resolution semantics.
- **Current Pain:** Must read existing plugins to understand implicit contracts. No way to test whether their dependency declarations are correct until they run a full Cobot instance.
- **Goal:** Declare dependencies in `PluginMeta` and have the system enforce them automatically. Get clear errors when something is missing.
- **Success Moment:** Adding `dependencies: ["telegram"]` to their plugin and seeing it automatically pull in Telegram when their plugin is a root.

### Secondary Users

**3. Cobot Core Maintainers**

- **Profile:** Contributors to the Cobot core who maintain the plugin system itself.
- **Need:** Clear resolution semantics, cycle detection, and diagnostic tooling to debug plugin loading issues.
- **Value:** Reduced issue reports from misconfiguration, clearer architecture for future plugin system enhancements.

### User Journey

1. **Discovery:** Operator reads docs or encounters a crash (like #227) and learns about root-based configuration.
2. **Configuration:** Operator sets `policy: disable` and lists only the plugins they want — deps resolve automatically. Or keeps `policy: enable` (default) and just uses `disabled` to exclude.
3. **Validation:** At startup, the resolver reports what's loading and why. Conflicts (enabled plugin needs a disabled dep) fail fast with actionable errors.
4. **Steady State:** Config changes are minimal and intentional. Adding a new capability means adding one root — the tree expands automatically.
5. **Plugin Development:** New plugin authors declare dependencies in metadata and test resolution without running a full instance.

---

## Success Metrics

### User Success Metrics

- **Zero misconfiguration crashes:** No runtime crashes from missing plugin dependencies. All dependency errors surface at config/resolution time.
- **Config simplicity:** Minimal configs need only 1-3 entries in `enabled` with `policy: disable` (vs. manually listing all transitive deps).
- **Resolution transparency:** Operator can see the full resolved dependency tree at startup via logs or CLI command.

### Business Objectives

- **Reduce support burden:** Eliminate the class of "why does my bot crash?" issues caused by plugin misconfiguration (Issue #227 and similar).
- **Lower onboarding friction:** New Cobot users can get a working configuration faster by declaring intent rather than manually curating plugin lists.
- **Enable plugin ecosystem growth:** Clear dependency semantics make it safer and easier to add new plugins without breaking existing configurations.

### Key Performance Indicators

| KPI | Target | Measurement |
|-----|--------|-------------|
| Misconfiguration-related crashes | 0 after migration | GitHub issues tagged plugin-system |
| Config migration success rate | >95% of existing configs migrate without manual intervention | Migration tool output |
| Plugin load time impact | <5% overhead from resolution | Benchmark: startup time before/after |
| Dependency cycle detection | 100% of cycles caught at resolution time | Test suite coverage |
| Plugin count supported | 50+ without performance degradation | Load testing |

---

## MVP Scope

### Core Features

1. **Dependency Tree Resolver**
   - Topological sort replacing current priority-based `_resolve_load_order()`
   - Cycle detection with clear error messages
   - Resolution from declared root plugins
   - Core plugins (`config`, `logger`, selected LLM provider) always loaded regardless of policy

2. **Load Policy**
   - New `policy` key: `enable` (default, everything loads) or `disable` (nothing loads by default)
   - `policy: enable` + `disabled` list = current behavior, now with dependency validation
   - `policy: disable` + `enabled` list = minimal mode, transitive deps auto-included
   - Provider selection integration (e.g., `provider: ppq` implies the PPQ plugin)

3. **Capability-Based Dependencies**
   - Plugins can depend on capabilities (e.g., `needs_capability: llm`) rather than specific IDs
   - Resolver selects the configured provider for abstract capability requirements

4. **Backward Compatibility**
   - Existing `enabled`/`disabled` configs continue working as-is (implicit `policy: enable`)
   - No breaking changes to existing setups
   - Dependency resolution is purely additive — same plugins load, but now with validation

5. **Startup Diagnostics**
   - Log the resolved dependency tree at startup
   - Warn about enabled-but-unreachable plugins
   - Clear error messages for missing dependencies and cycles

### Out of Scope for MVP

- **Hot reload / runtime dependency changes** — plugins load once at startup
- **Plugin marketplace or external plugin packaging** — only local plugins
- **Dependency version constraints** — `PluginMeta.version` exists but version resolution is deferred
- **Visual dependency graph tooling** — text-based diagnostics only
- **`optional_dependencies` resolution** — validated but not used to drive loading (existing behavior preserved)
- **Multi-loop coordination semantics** — multiple loop plugins work independently; shared event loop coordination is existing behavior

### MVP Success Criteria

- Issue #227 scenario resolved by design — `policy: disable` + `enabled: [telegram_lurker]` loads only telegram_lurker and its deps, no loop plugin
- All 30 existing plugins' dependency declarations produce valid resolution trees
- Existing configs with `enabled`/`disabled` continue to work unchanged
- At least one example config using `policy: disable` in documentation
- `_resolve_load_order()` TODO for topological sort is resolved

### Future Vision

- **Dependency graph CLI:** `cobot plugins resolve --config cobot.yml` to preview what would load without starting
- **Version-aware resolution:** Use `PluginMeta.version` for compatibility checks
- **Optional dependency promotion:** Smart loading of optional dependencies when available
- **Plugin groups / profiles:** Named configuration profiles (e.g., `profile: archiver`, `profile: agent`)
- **Extension point validation:** Use `extension_points` and `implements` metadata for interface contract checking
- **Runtime dependency management:** Dynamic plugin loading/unloading with dependency-aware lifecycle

---

## Risks and Constraints

### Technical Risks

- **Incomplete dependency declarations:** Existing plugins may have undeclared implicit dependencies. Migration requires auditing all 30 plugins.
- **Circular dependencies:** Currently undetected. The resolver must handle cycles gracefully.
- **Performance:** Topological sort on 30 plugins is trivial, but the resolver must not add significant startup latency.

### Constraints

- **Python-only:** Resolution engine must be pure Python, no external dependency solvers.
- **Single-process model:** Cobot runs as one process; resolution doesn't need to consider distributed loading.
- **Backward compatibility is mandatory:** Existing deployments must not break.

---

*Product Brief complete. This document provides the strategic foundation for developing a detailed PRD and technical architecture for Cobot's plugin dependency tree resolution system.*
