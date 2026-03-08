---
title: "Product Requirements Document: Cobot Plugin Dependency Tree Resolution"
date: 2026-03-08
author: BMad Master
version: "1.0"
status: draft
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
classification:
  projectType: "library/framework-internal"
  domain: "developer-tools"
  complexity: "medium"
  projectContext: "brownfield"
documentCounts:
  briefCount: 1
  researchCount: 0
  brainstormingCount: 0
  projectDocsCount: 1
---

# Product Requirements Document
## Cobot Plugin Dependency Tree Resolution

---

## 1. Executive Summary

Cobot's plugin system currently loads plugins from a flat enabled/disabled list with no dependency-tree resolution. All enabled plugins load regardless of whether they're actually needed, leading to runtime crashes (Issue #227), fragile configurations, and wasted resources.

This PRD specifies the addition of **load policy and transitive dependency resolution** to the Cobot plugin system. Users declare intent via a `policy` field (`enable` or `disable`) combined with `enabled`/`disabled` lists. The system resolves transitive dependencies downward from enabled plugins, detects conflicts at startup, and replaces the current priority-based load ordering with topological sort.

**Key outcome:** Configurations become self-documenting, crash-free, and minimal. Existing configs work unchanged (backward compatible via implicit `policy: enable`).

---

## 2. Problem Statement

### 2.1 Current State

The plugin loading pipeline in `cobot/plugins/__init__.py` follows this sequence:

```
discover_plugins(dir) → filter(enabled/disabled) → register → configure → start
```

Key observations from the source code:

- **`discover_plugins()`** scans plugin directories and imports all `plugin.py` files with a `create_plugin()` factory
- **Filtering** is a flat list match: if `enabled_list` is set, only those + core plugins load; `disabled_list` excludes specific plugins
- **`_resolve_load_order()`** in `registry.py` sorts by `priority` field only, with an explicit `TODO: Topological sort for dependencies` comment
- **`_check_dependencies()`** validates post-registration that declared dependencies exist, but never drives what should load
- **Core plugins** (`config`, `logger`, selected LLM provider) always load regardless of lists

### 2.2 The 29 Plugins — Dependency Map

From source code analysis, the current plugin inventory and their declared dependencies:

| Plugin | Dependencies | Capabilities | Priority |
|--------|-------------|--------------|----------|
| config | — | config | 1 |
| logger | — | logging | 5 |
| cli | — | — | 5 |
| workspace | config | workspace | 5 |
| communication | — | — | 5 |
| pairing | config | pairing | 5 |
| security | config | security | 10 |
| memory | workspace | — | 12 |
| memory-files | workspace, memory | — | 14 |
| soul | workspace | — | 15 |
| persistence | config, workspace | persistence | 15 |
| compaction | config, persistence | compaction | 16 |
| trust | config | — | 16 |
| context | config | — | 18 |
| skills | config | tools | 19 |
| ppq | config | llm | 20 |
| ollama | config | llm | 20 |
| knowledge | config | knowledge, tools | 22 |
| filedrop | config | communication | 24 |
| nostr | config | communication | 25 |
| wallet | config | wallet, tools | 25 |
| session | communication | — | (default) |
| telegram | session | communication | 30 |
| tools | config | tools | 30 |
| web | config | — | 30 |
| subagent | config | subagent, tools | 32 |
| cron | config | cron, tools | 40 |
| heartbeat | cron | — | 45 |
| loop | config, communication | loop | (default) |

### 2.3 Problem Impact

1. **Runtime crashes (Issue #227):** Enabling `telegram` + `telegram_lurker` without `loop` causes `agent.run_loop()` to crash. Plugins load successfully — the failure is silent until execution.
2. **Configuration fragility:** Users must understand internal plugin interdependencies to write valid configs. No guardrails exist.
3. **Wasted resources:** All enabled plugins load, configure, and start — even those unreachable from any active use case.
4. **Maintenance burden:** With 29 plugins, the implicit dependency web is increasingly hard to reason about. PR #228 is a bandaid.

### 2.4 Why Current Solutions Fall Short

- **`_check_dependencies()`** validates post-registration only — never drives loading decisions
- **`_resolve_load_order()`** uses priority-based sorting with an acknowledged TODO for topological sort
- **PR #228** makes `agent.py` tolerant of missing loop plugins — papers over the symptom
- **Manual plugin curation** doesn't scale and provides no feedback on incomplete configurations

---

## 3. Product Vision

Transform Cobot's plugin loading from "load everything enabled" to "load what's needed" — making configurations predictable, crash-free, and self-documenting while maintaining full backward compatibility.

---

## 4. Goals and Non-Goals

### 4.1 Goals

| # | Goal | Success Criteria |
|---|------|-----------------|
| G1 | Transitive dependency resolution | Enabling plugin A that depends on B auto-loads B |
| G2 | Load policy support | `policy: enable` (default) and `policy: disable` modes |
| G3 | Conflict detection at startup | Enabled plugin requiring disabled dep → hard error before any plugin starts |
| G4 | Topological load ordering | Replace priority-based sort with dependency-aware topological sort |
| G5 | Full backward compatibility | Existing configs with `enabled`/`disabled` work unchanged |
| G6 | Startup diagnostics | Log resolved dependency tree, warn about unreachable plugins |

### 4.2 Non-Goals

- **Hot reload / runtime dependency changes** — plugins load once at startup
- **Plugin marketplace or external plugin packaging** — only local + pip-installed plugins
- **Dependency version constraints** — `PluginMeta.version` exists but version resolution is deferred
- **Visual dependency graph tooling** — text-based diagnostics only for MVP
- **`optional_dependencies` resolution** — validated but not used to drive loading (existing behavior)
- **Multi-loop coordination** — out of scope; existing independent operation preserved
- **"Roots" concept** — there are no special "root" plugins; enabled plugins ARE the entry points

---

## 5. Design Decisions (Normative)

These decisions are authoritative and override any conflicting information in input documents:

### DD1: No "Roots" Concept
Enabled plugins ARE the entry points. There is no separate `roots` config key. Dependencies resolve downward only from whatever plugins are determined to be enabled by the load policy.

### DD2: Load Policy
```yaml
plugins:
  policy: enable    # Default. Load all discovered plugins. Use `disabled` to exclude.
  # OR
  policy: disable   # Load nothing by default. Use `enabled` to include.
```

- `policy: enable` (default when `policy` is absent) — all plugins load, `disabled` list excludes specific ones
- `policy: disable` — no plugins load by default, `enabled` list includes specific ones
- In both modes, **core plugins** (`config`, `logger`, selected LLM provider) always load

### DD3: Transitive Dependencies
If plugin A is enabled (by policy or explicit list) and A declares `dependencies: ["B"]`, then B is auto-loaded even if not explicitly listed. B being loaded does NOT auto-load A — dependencies flow downward only.

### DD4: Conflict = Hard Error
If a plugin that would be loaded (directly or transitively) requires a dependency that is explicitly disabled, the system raises a hard error at startup with a clear message. No silent fallback.

### DD5: Backward Compatible
Existing configs without a `policy` key work as-is. The implicit default is `policy: enable`, which preserves current behavior (load everything, respect `disabled` list). Dependency resolution adds validation but doesn't change what loads for existing configs.

---

## 6. User Stories

### US1: Minimal Headless Bot (The Deployer)
**As** a Cobot operator deploying an archival Telegram lurker,
**I want** to set `policy: disable` and `enabled: [telegram]`,
**So that** only `telegram` and its transitive dependencies load (session → communication → config), with no loop plugin, no crashes.

**Acceptance Criteria:**
- Setting `policy: disable` + `enabled: [telegram]` loads exactly: config, logger, selected LLM provider, communication, session, telegram
- No loop plugin loads → no crash in `agent.run_loop()` (headless mode works)
- Startup log shows resolved tree

### US2: Full Agent with Exclusions (The Deployer)
**As** a Cobot operator running a full agent,
**I want** to keep the default `policy: enable` and disable specific plugins,
**So that** my existing config continues working with added safety of dependency validation.

**Acceptance Criteria:**
- `policy: enable` + `disabled: [ollama, nostr]` loads all plugins except ollama and nostr
- If any loaded plugin depends on ollama or nostr, startup fails with a clear error message
- Behavior identical to current system for valid configs

### US3: Dependency Conflict Detection (The Deployer)
**As** a Cobot operator,
**I want** the system to tell me at startup if my config is contradictory,
**So that** I don't discover missing dependencies at runtime.

**Acceptance Criteria:**
- `policy: disable` + `enabled: [heartbeat]` + `disabled: [cron]` → error: "heartbeat requires cron, which is disabled"
- Error occurs before any plugin starts
- Error message names the full dependency chain

### US4: Plugin Development (The Extender)
**As** a plugin developer,
**I want** to declare `dependencies` in `PluginMeta` and have them automatically resolved,
**So that** my plugin's requirements are enforced without users needing to know about them.

**Acceptance Criteria:**
- New plugin with `dependencies: ["telegram"]` — when enabled, telegram and its deps auto-load
- Missing dependency (not installed) produces clear error
- Cycle between two plugins produces clear error at resolution time

### US5: Startup Transparency (The Maintainer)
**As** a Cobot core maintainer,
**I want** to see the resolved dependency tree at startup,
**So that** I can debug plugin loading issues quickly.

**Acceptance Criteria:**
- Startup log shows which plugins loaded and why (direct enable, transitive dep, core)
- Plugins that were discovered but not loaded are listed with reason (disabled, not reachable)
- Dependency cycles are reported with the full cycle path

---

## 7. Functional Requirements

### FR1: Load Policy Engine

**FR1.1:** Add `policy` field to plugins config section. Valid values: `"enable"` (default), `"disable"`.

**FR1.2:** When `policy: enable` (or absent):
- Start with all discovered plugin classes
- Remove any in `disabled` list
- Remove LLM providers that don't match `provider` selection
- Core plugins always included

**FR1.3:** When `policy: disable`:
- Start with empty set
- Add plugins in `enabled` list
- Add core plugins (`config`, `logger`, selected LLM provider)
- Add transitive dependencies of all included plugins (FR2)

**FR1.4:** In both modes, apply transitive dependency resolution (FR2) after the initial set is determined.

### FR2: Transitive Dependency Resolution

**FR2.1:** After determining the initial plugin set (from FR1), resolve transitive dependencies:
- For each plugin in the set, add all plugins listed in its `dependencies` field
- Recurse until no new plugins are added
- Dependencies flow downward only: loading B because A needs it does NOT add A's dependents

**FR2.2:** Resolution must handle:
- Direct dependencies: A → B
- Transitive chains: A → B → C
- Diamond dependencies: A → B, A → C, B → D, C → D (D loaded once)
- Self-referential dependencies: A → A (error)

### FR3: Conflict Detection

**FR3.1:** After resolution, check for conflicts:
- A resolved plugin requires a dependency that is in the `disabled` list → **hard error**
- A resolved plugin requires a dependency that is not discovered (not installed) → **hard error**

**FR3.2:** Error messages must include:
- The plugin that needs the dependency
- The missing/disabled dependency name
- The full chain if transitive (e.g., "heartbeat → cron: cron is disabled")

**FR3.3:** All conflicts detected before any plugin is registered, configured, or started.

### FR4: Cycle Detection

**FR4.1:** During dependency resolution, detect circular dependencies.

**FR4.2:** Cycles produce a hard error with the full cycle path (e.g., "Cycle detected: A → B → C → A").

**FR4.3:** Implementation: standard DFS-based cycle detection during topological sort.

### FR5: Topological Load Ordering

**FR5.1:** Replace `_resolve_load_order()` priority-based sort with topological sort based on declared `dependencies`.

**FR5.2:** Within the same topological level (no dependency ordering between them), use existing `priority` field as tiebreaker.

**FR5.3:** This resolves the existing `TODO: Topological sort for dependencies` in `registry.py`.

### FR6: Capability-Based Dependencies

**FR6.1:** Plugins may depend on capabilities (e.g., `needs_capability: ["llm"]`) in addition to specific plugin IDs.

**FR6.2:** The resolver maps capability requirements to the concrete plugin providing that capability (e.g., `llm` → `ppq` when `provider: ppq`).

**FR6.3:** If no plugin in the resolved set provides a required capability, raise a hard error.

**FR6.4:** MVP scope: implement for the `llm` provider selection pattern already in code. Generalize in future iterations.

### FR7: Startup Diagnostics

**FR7.1:** Log the resolved plugin set at startup with load reason:
- `[direct]` — explicitly in `enabled` list or included by `policy: enable`
- `[transitive]` — loaded as dependency of another plugin
- `[core]` — always-load core plugin

**FR7.2:** Log plugins that were discovered but not loaded, with reason:
- `[disabled]` — in `disabled` list
- `[not-reachable]` — not in dependency tree (only in `policy: disable` mode)
- `[provider-skip]` — LLM provider not selected

**FR7.3:** Log the topological load order.

---

## 8. Non-Functional Requirements

### NFR1: Performance
- Dependency resolution must complete in <50ms for 50 plugins
- Overall startup time impact <5% compared to current flat loading
- Resolution is O(V+E) with standard topological sort — trivially fast for the scale

### NFR2: Backward Compatibility
- Existing `cobot.yml` files without `policy` key must work identically to current behavior
- No changes to `PluginMeta` dataclass structure (only new optional fields)
- No changes to plugin `configure()`, `start()`, `stop()` interfaces
- External plugins loaded via `load_external_plugins()` participate in resolution

### NFR3: Error Quality
- All error messages must be actionable: state what's wrong, why, and how to fix it
- Error messages reference config keys and plugin IDs, not internal code
- Errors surface at startup (fail-fast), never at runtime

### NFR4: Testability
- Resolution logic must be pure functions testable without plugin instantiation
- Test coverage: cycle detection, transitive resolution, conflict detection, all policy modes
- Existing plugin test suites must pass unchanged

---

## 9. Technical Architecture

### 9.1 Component Overview

The change is primarily in two files:

**`cobot/plugins/__init__.py`** — `init_plugins()` function:
- Add policy parsing from `plugins_config`
- Replace flat filtering with resolution engine call
- Pass resolved set to registration loop

**`cobot/plugins/registry.py`** — `PluginRegistry`:
- Replace `_resolve_load_order()` with topological sort
- Enhanced `_check_dependencies()` integrated into resolution

**New module: `cobot/plugins/resolver.py`**:
- Pure function: `resolve(discovered_plugins, policy, enabled, disabled, provider, core_plugins) → ResolvedSet`
- Contains: topological sort, cycle detection, transitive resolution, conflict checking
- Returns: ordered list of plugin classes to load + diagnostic info

### 9.2 Resolution Algorithm

```python
def resolve(
    discovered: dict[str, type[Plugin]],  # id → class
    policy: str,                           # "enable" | "disable"
    enabled: list[str],
    disabled: list[str],
    provider: str,
    core_ids: list[str],
) -> ResolveResult:
    """
    1. Determine initial set based on policy
    2. Add core plugins
    3. Filter LLM providers (keep only selected)
    4. Resolve transitive dependencies (BFS/DFS from initial set)
    5. Check for conflicts (resolved dep in disabled list)
    6. Detect cycles (DFS with coloring)
    7. Topological sort (Kahn's algorithm, priority as tiebreaker)
    8. Return ordered list + diagnostics
    """
```

### 9.3 Data Flow

```
cobot.yml
    ↓
parse config: policy, enabled, disabled, provider
    ↓
discover_plugins() → dict of all plugin classes
    ↓
resolve() → ordered list + diagnostics
    ↓
register in order → configure → start
```

### 9.4 Config Schema Changes

```yaml
# Current (still works):
plugins:
  enabled: [telegram, web]
  disabled: [ollama]

# New:
plugins:
  policy: enable          # NEW — default if absent
  enabled: [telegram]     # Meaning changes with policy
  disabled: [ollama]      # Only valid with policy: enable
  external: [...]         # Unchanged
```

Validation rules:
- `policy: enable` + `enabled` list → warning (unusual but valid; means "load all but prioritize these"... actually in enable-all mode, `enabled` has no additional effect — warn user)
- `policy: disable` + `disabled` list → error (contradictory: you're disabling by default, then also disabling specific ones)
- `policy: disable` + no `enabled` list → only core plugins load (valid but probably unintended — warn)

### 9.5 Impact on Existing Code

| File | Change |
|------|--------|
| `cobot/plugins/__init__.py` | Refactor `init_plugins()` filtering to use resolver |
| `cobot/plugins/registry.py` | Replace `_resolve_load_order()` with topological sort |
| `cobot/plugins/resolver.py` | **New** — resolution engine |
| `cobot/plugins/base.py` | No changes to `PluginMeta` or `Plugin` |
| `cobot/agent.py` | No changes (benefits from correct loading) |
| Plugin `plugin.py` files | No changes (existing `dependencies` declarations used as-is) |

---

## 10. Migration Plan

### 10.1 Phase 1: Non-Breaking Addition
1. Add `resolver.py` with resolution logic
2. Refactor `init_plugins()` to use resolver when `policy` key is present
3. When `policy` is absent, behavior is identical to current (implicit `policy: enable`)
4. Add topological sort to `_resolve_load_order()`

### 10.2 Phase 2: Dependency Audit
1. Audit all 29 plugins for undeclared implicit dependencies
2. Add missing `dependencies` declarations to `PluginMeta`
3. Ensure all dependency chains resolve correctly with current configs

### 10.3 Phase 3: Documentation & Adoption
1. Document `policy` config option
2. Add example configs for common use cases (full agent, headless lurker, web-only)
3. Add `cobot plugins resolve` CLI command to preview resolution without starting

### 10.4 Backward Compatibility Guarantee
- Existing configs without `policy` key: **zero behavior change**
- Existing configs with `enabled`/`disabled`: same plugins load, now with dependency validation
- If dependency validation reveals issues in existing configs: log warnings, don't error (for Phase 1)

---

## 11. Testing Strategy

### 11.1 Unit Tests (resolver.py)

| Test Case | Input | Expected |
|-----------|-------|----------|
| Empty resolve | policy=disable, enabled=[] | Only core plugins |
| Single plugin, no deps | policy=disable, enabled=[web] | web + core |
| Transitive chain | policy=disable, enabled=[heartbeat] | heartbeat → cron → config + core |
| Diamond dependency | A→B, A→C, B→D, C→D | D loaded once |
| Cycle detection | A→B, B→A | Error with cycle path |
| Conflict: disabled dep | enabled=[heartbeat], disabled=[cron] | Error: heartbeat needs cron |
| Policy enable + disabled | policy=enable, disabled=[nostr] | All except nostr |
| Missing plugin | enabled=[nonexistent] | Error: plugin not found |
| Provider selection | provider=ppq | ppq loads, ollama skipped |
| Backward compat | no policy key | Same as policy=enable |

### 11.2 Integration Tests
- Full `init_plugins()` with resolver in both policy modes
- Existing test configs produce identical plugin sets
- Startup diagnostics logged correctly

### 11.3 Regression Tests
- All existing plugin tests pass unchanged
- Issue #227 scenario resolved by design

---

## 12. Success Metrics

| KPI | Target | Measurement |
|-----|--------|-------------|
| Misconfiguration crashes | 0 after migration | GitHub issues tagged plugin-system |
| Config migration success | >95% existing configs work unchanged | Automated test |
| Startup time impact | <5% overhead | Benchmark before/after |
| Cycle detection coverage | 100% of cycles caught | Test suite |
| Plugin count supported | 50+ without degradation | Load test |

---

## 13. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Undeclared implicit dependencies in existing plugins | High | Medium | Dependency audit in Phase 2; warnings not errors in Phase 1 |
| Circular dependencies in existing plugins | Low | High | Cycle detection with clear error messages |
| Config confusion (policy semantics) | Medium | Low | Clear documentation, startup warnings for unusual combos |
| Performance regression | Very Low | Low | Resolution is O(V+E) on ~30 nodes; benchmark to verify |

---

## 14. Open Questions

1. **`optional_dependencies` semantics in resolution:** Currently validated but not used for loading. Should `policy: disable` mode auto-load optional deps if they're available? **Recommendation:** No for MVP — keep current behavior.

2. **`consumes` field:** Several plugins declare `consumes: ["llm"]` or `consumes: ["tools"]`. Should this be treated as a dependency during resolution? **Recommendation:** Not for MVP — `consumes` is a runtime lookup pattern, not a hard dependency.

3. **Provider selection generalization:** Currently only LLM providers have the `provider` selection pattern. Should this generalize to other capability types? **Recommendation:** Defer — solve LLM provider selection in FR6, generalize later if needed.

---

## 15. Future Vision

- **Dependency graph CLI:** `cobot plugins resolve --config cobot.yml` to preview resolution
- **Version-aware resolution:** Use `PluginMeta.version` for compatibility checks
- **Plugin profiles:** Named config presets (e.g., `profile: archiver`, `profile: agent`)
- **Extension point validation:** Use `extension_points`/`implements` for interface contract checking
- **Optional dependency promotion:** Smart loading of optional dependencies when available
- **Runtime dependency management:** Dynamic plugin loading/unloading

---

*PRD complete. This document provides the complete requirements for implementing plugin dependency tree resolution in Cobot.*
