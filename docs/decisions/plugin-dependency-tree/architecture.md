---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - docs/decisions/plugin-dependency-tree/product-brief.md
  - docs/decisions/plugin-dependency-tree/prd.md
  - /olymp/shared/files/prd-draft-plugin-dependency-tree.md
workflowType: 'architecture'
project_name: 'Cobot Plugin Dependency Tree Resolution'
date: '2026-03-08'
---

# Architecture Decision Document
## Cobot Plugin Dependency Tree Resolution

_This document defines the technical architecture for adding load policy and transitive dependency resolution to Cobot's plugin system._

---

## 1. Project Context Analysis

### Requirements Overview

**Functional Requirements:**
The PRD specifies 7 functional requirement groups (FR1–FR7): Load Policy Engine, Transitive Dependency Resolution, Conflict Detection, Cycle Detection, Topological Load Ordering, Capability-Based Dependencies, and Startup Diagnostics. All are internal to the plugin loading pipeline — no new user-facing features, no new APIs, no new services.

**Non-Functional Requirements:**
- Resolution must complete in <50ms for 50 plugins (O(V+E) — trivially met)
- <5% startup time overhead
- Full backward compatibility with existing `cobot.yml` configs
- All errors must be actionable and surface at startup (fail-fast)

**Scale & Complexity:**
- Primary domain: Python library internals (plugin framework)
- Complexity level: Medium — well-scoped graph algorithm work in existing codebase
- Affected components: 3 files modified, 1 new file

### Technical Constraints & Dependencies

- **Python-only** — no external dependency solvers
- **Single-process model** — no distributed concerns
- **Existing `PluginMeta` dataclass** already declares `dependencies`, `optional_dependencies`, `capabilities`, `consumes`, and `priority` — the data model is ready
- **29 built-in plugins** with declared dependency chains (see inventory below)
- **External plugins** via `load_external_plugins()` must participate in resolution

### Cross-Cutting Concerns

1. **Backward compatibility** — implicit `policy: enable` must produce identical behavior to current code
2. **Error messaging** — all new error paths must produce user-actionable messages referencing config keys
3. **Logging** — resolution happens before the logger plugin starts; must use `_early_log()` fallback
4. **Testing** — resolver must be testable as pure functions without plugin instantiation

---

## 2. Starter Template Evaluation

### Primary Technology Domain

This is a **brownfield enhancement** to an existing Python project. No starter template needed — we're modifying `cobot/plugins/` within the existing Cobot codebase.

### Technology Stack (Existing)

- **Language:** Python 3.11+ with type hints
- **Package structure:** `cobot.plugins` subpackage
- **Testing:** pytest (existing test suite)
- **No external dependencies** required for the resolver — pure Python graph algorithms

### Selected Approach: New Module + Refactor

Rather than a starter template, the architecture adds one new module (`resolver.py`) and refactors two existing modules (`__init__.py`, `registry.py`). This preserves the existing project structure entirely.

---

## 3. Core Architectural Decisions

### AD1: Resolver as Pure Function Module

**Decision:** Create `cobot/plugins/resolver.py` containing pure functions for dependency resolution, separate from the registry's stateful plugin management.

**Rationale:**
- Pure functions are trivially testable without plugin instantiation
- Clean separation: resolver computes *what* to load; registry manages *how* to load
- The current `_resolve_load_order()` and `_check_dependencies()` in `registry.py` mix resolution concerns with registry state — this untangles them

**Implementation:**
```python
# cobot/plugins/resolver.py

@dataclass
class PluginNode:
    """Lightweight plugin representation for resolution (no instantiation needed)."""
    id: str
    dependencies: list[str]
    optional_dependencies: list[str]
    capabilities: list[str]
    consumes: list[str]
    priority: int

@dataclass
class ResolveResult:
    """Resolution output."""
    load_order: list[str]           # Topologically sorted plugin IDs to load
    load_reasons: dict[str, str]    # plugin_id → "direct" | "transitive" | "core"
    skipped: dict[str, str]         # plugin_id → reason not loaded
    warnings: list[str]             # Non-fatal diagnostics

def resolve(
    discovered: dict[str, PluginNode],
    policy: str,            # "enable" | "disable"
    enabled: list[str],
    disabled: list[str],
    provider: str,
    core_ids: list[str],
) -> ResolveResult:
    ...
```

### AD2: Two-Phase Resolution Algorithm

**Decision:** Resolution proceeds in two phases: (1) determine the enabled set, (2) resolve transitive dependencies and produce topological order.

**Phase 1 — Determine Enabled Set:**
```
if policy == "enable" (default):
    enabled_set = all_discovered - disabled - non_selected_llm_providers
elif policy == "disable":
    enabled_set = enabled_list + core_ids
```

**Phase 2 — Transitive Resolution + Topological Sort:**
```
1. Starting from enabled_set, BFS/DFS to collect all transitive dependencies
2. For each dep found: if in disabled list → hard error (conflict)
3. For each dep found: if not in discovered → hard error (missing)
4. Detect cycles via DFS with 3-color marking (white/gray/black)
5. Topological sort via Kahn's algorithm with priority as tiebreaker within same level
```

**Rationale:**
- Phase separation makes each concern testable independently
- BFS for transitive deps is natural and handles diamonds (A→B→D, A→C→D) automatically via visited set
- Kahn's algorithm produces stable ordering and naturally detects remaining cycles
- Priority tiebreaker preserves existing behavior for plugins with no dependency relationship

### AD3: No "Roots" Concept

**Decision:** There is no `roots` config key. Enabled plugins ARE the entry points. Dependencies resolve downward only.

**Rationale:** Per design decision DD1 from the PRD. The enabled set (determined by policy) serves as the set of "roots" for transitive resolution. This avoids introducing a new concept and keeps the config model minimal.

### AD4: Core Plugins Always Load

**Decision:** `config`, `logger`, and the selected LLM provider (from `provider` key) always load regardless of policy or disabled list.

**Rationale:** This matches current behavior in `init_plugins()`. These plugins are infrastructure — config provides settings, logger provides diagnostics, and the LLM provider is selected by a dedicated `provider` key rather than the `enabled`/`disabled` mechanism.

**Implementation detail:** Core plugin IDs are injected into the enabled set before resolution begins. If a core plugin is in the `disabled` list, emit a warning and load it anyway (don't error — this preserves backward compat for configs that might disable `ollama` when using `ppq`).

### AD5: Conflict Detection = Hard Error

**Decision:** If transitive resolution requires a plugin that is explicitly in the `disabled` list, raise `PluginError` before any plugin is registered.

**Error format:**
```
PluginError: Plugin 'heartbeat' requires 'cron', which is disabled.
  Chain: heartbeat → cron
  Fix: Remove 'cron' from plugins.disabled, or remove 'heartbeat' from plugins.enabled.
```

**Rationale:** Per DD4 from the PRD. Silent fallbacks create the exact class of runtime crashes this project eliminates.

### AD6: Topological Sort Replaces Priority Sort

**Decision:** Replace `_resolve_load_order()` in `registry.py` with topological sort from the resolver, using `priority` as tiebreaker for unrelated plugins.

**Current code (`registry.py:_resolve_load_order`):**
```python
def _resolve_load_order(self) -> list[str]:
    sorted_ids = sorted(
        self._plugins.keys(), key=lambda pid: self._plugins[pid].meta.priority
    )
    # TODO: Topological sort for dependencies
    return sorted_ids
```

**New behavior:** The resolver produces the load order. `_resolve_load_order()` is removed from `PluginRegistry` (or delegated to the resolver). The registry receives the pre-computed order.

### AD7: `optional_dependencies` — No Auto-Loading

**Decision:** `optional_dependencies` are NOT used to drive loading. They are validated if both plugins happen to be loaded (existing behavior), but an optional dep being available does NOT cause it to auto-load.

**Rationale:** Per PRD non-goal. Optional deps are a runtime convenience ("use if present"), not a loading directive. Auto-loading optional deps would defeat the purpose of `policy: disable` mode.

### AD8: `consumes` — Not a Dependency

**Decision:** The `consumes` field (e.g., `loop` consumes `["llm", "tools"]`) is NOT treated as a hard dependency during resolution.

**Rationale:** `consumes` is a runtime capability lookup pattern. The loop plugin *uses* LLM providers but doesn't *depend* on a specific one — the provider is selected by the separate `provider` config key. Treating `consumes` as dependency would create false circular dependencies (e.g., loop consumes tools, tools plugin exists).

### AD9: Config Validation Rules

**Decision:** Validate config combinations and warn/error on problematic ones:

| Config | Behavior |
|--------|----------|
| No `policy` key | Implicit `policy: enable` (backward compat) |
| `policy: enable` + `enabled` list | Warning: "In enable-all mode, `enabled` has no additional effect" |
| `policy: disable` + `disabled` list | Error: "Cannot use `disabled` with `policy: disable`" |
| `policy: disable` + no `enabled` list | Warning: "Only core plugins will load" |
| Unknown `policy` value | Error: "Invalid policy: must be 'enable' or 'disable'" |

---

## 4. Implementation Patterns & Consistency Rules

### Pattern 1: Error Messages Reference Config, Not Code

All `PluginError` messages raised by the resolver must reference `cobot.yml` config keys and plugin IDs, never internal variable names or file paths.

**Good:** `Plugin 'heartbeat' requires 'cron', which is in plugins.disabled`
**Bad:** `KeyError in _resolve_transitive: 'cron' not in discovered dict`

### Pattern 2: Logging Before Logger

Resolution runs before the logger plugin starts. All resolver logging uses the existing `_early_log()` pattern from `__init__.py` (writes to stderr with consistent format).

### Pattern 3: Immutable Resolution

The `resolve()` function receives immutable inputs and returns a new `ResolveResult`. It never mutates the discovered plugin dict or config. This makes it safe to call multiple times (e.g., for dry-run/preview).

### Pattern 4: Test Without Instantiation

Tests create `PluginNode` objects directly — no need to import actual plugin classes, instantiate plugins, or have plugin dependencies available. This enables fast, isolated unit tests.

```python
# Example test
def test_transitive_chain():
    discovered = {
        "heartbeat": PluginNode(id="heartbeat", dependencies=["cron"], ...),
        "cron": PluginNode(id="cron", dependencies=["config"], ...),
        "config": PluginNode(id="config", dependencies=[], ...),
        "logger": PluginNode(id="logger", dependencies=[], ...),
    }
    result = resolve(discovered, policy="disable", enabled=["heartbeat"],
                     disabled=[], provider="ppq", core_ids=["config", "logger"])
    assert result.load_order == ["config", "logger", "cron", "heartbeat"]
```

### Pattern 5: Diagnostic Transparency

Every plugin in the resolved set gets a load reason. Every discovered-but-not-loaded plugin gets a skip reason. This is logged at startup and available programmatically via `ResolveResult`.

```
[I] [resolver    ] Resolved 8 plugins (policy: disable)
[I] [resolver    ] Loading: config [core], logger [core], ppq [core],
                    workspace [transitive], session [transitive],
                    communication [transitive], telegram [direct], loop [direct]
[I] [resolver    ] Skipped: ollama [provider-skip], nostr [not-reachable],
                    heartbeat [not-reachable], cron [not-reachable], ...
```

---

## 5. Project Structure & Boundaries

### Modified Files

```
cobot/plugins/
├── __init__.py          # MODIFIED — init_plugins() uses resolver
├── base.py              # UNCHANGED
├── interfaces.py        # UNCHANGED
├── registry.py          # MODIFIED — _resolve_load_order() removed, receives order
├── resolver.py          # NEW — pure resolution engine
└── [plugin dirs]/       # UNCHANGED
    └── plugin.py

tests/
├── test_resolver.py     # NEW — unit tests for resolver
├── test_init_plugins.py # MODIFIED — integration tests with resolver
└── test_registry.py     # MODIFIED — updated for new load order behavior
```

### Module Boundaries

```
┌─────────────────────────────────────────────────────┐
│                    init_plugins()                     │
│                  (__init__.py)                        │
│                                                       │
│  1. discover_plugins() → plugin_classes              │
│  2. load_external_plugins() → more plugin_classes    │
│  3. Build PluginNode dict from classes               │
│  4. Parse policy/enabled/disabled from config        │
│  5. Call resolve() ──────────────────────┐           │
│  6. Register only resolved plugins       │           │
│  7. configure_all() + start_all()        │           │
└──────────────────────────────────────────┼───────────┘
                                           │
              ┌────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────┐
│                    resolve()                          │
│                  (resolver.py)                        │
│                                                       │
│  Input:  discovered: dict[str, PluginNode]           │
│          policy, enabled, disabled, provider, core   │
│                                                       │
│  Output: ResolveResult                                │
│          - load_order: list[str]                     │
│          - load_reasons: dict[str, str]              │
│          - skipped: dict[str, str]                   │
│          - warnings: list[str]                       │
│                                                       │
│  Internal:                                            │
│   _determine_enabled_set()                           │
│   _resolve_transitive()                              │
│   _detect_cycles()                                   │
│   _topological_sort()                                │
│   _check_conflicts()                                 │
└─────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────┐
│                  PluginRegistry                       │
│                  (registry.py)                        │
│                                                       │
│  - Receives pre-computed load order                  │
│  - register() / configure_all() / start_all()       │
│  - _resolve_load_order() REMOVED                     │
│  - _check_dependencies() REMOVED (resolver handles) │
│  - set_load_order(order: list[str]) NEW              │
└─────────────────────────────────────────────────────┘
```

### Data Flow Detail

```
cobot.yml
    │
    ▼
config = {
    "provider": "ppq",
    "plugins": {
        "policy": "disable",        # NEW field
        "enabled": ["telegram", "loop"],
        "disabled": [],
        "external": ["cobot_telegram_lurker"]
    }
}
    │
    ▼
discover_plugins(dir) + load_external_plugins(external)
    │
    ▼
plugin_classes: list[type[Plugin]]
    │
    ▼  (extract metadata, no instantiation)
discovered: dict[str, PluginNode] = {
    "config":        PluginNode(id="config", deps=[], caps=["config"], pri=1),
    "logger":        PluginNode(id="logger", deps=[], caps=["logging"], pri=5),
    "workspace":     PluginNode(id="workspace", deps=["config"], caps=["workspace"], pri=5),
    "communication": PluginNode(id="communication", deps=[], caps=[], pri=5),
    "session":       PluginNode(id="session", deps=["communication"], caps=[], pri=50),
    "telegram":      PluginNode(id="telegram", deps=["session"], caps=["communication"], pri=30),
    "loop":          PluginNode(id="loop", deps=["config","communication"], caps=["loop"], pri=50),
    ...
}
    │
    ▼
resolve(discovered, policy="disable", enabled=["telegram","loop"], ...)
    │
    ▼
ResolveResult:
    load_order: ["config", "logger", "ppq", "communication", "session", "telegram", "loop"]
    load_reasons: {
        "config": "core", "logger": "core", "ppq": "core",
        "communication": "transitive", "session": "transitive",
        "telegram": "direct", "loop": "direct"
    }
    skipped: {"ollama": "provider-skip", "nostr": "not-reachable", ...}
    │
    ▼
Register + configure + start (only resolved plugins, in resolved order)
```

---

## 6. Complete Plugin Dependency Graph

Source-verified from all 29 `plugin.py` files:

```
config (pri=1, caps=[config], deps=[])
├── logger (pri=5, caps=[logging], deps=[])
├── cli (pri=5, caps=[], deps=[])
├── workspace (pri=5, caps=[workspace], deps=[config])
│   ├── memory (pri=12, caps=[], deps=[workspace])
│   │   └── memory-files (pri=14, caps=[], deps=[workspace, memory])
│   ├── soul (pri=15, caps=[], deps=[workspace])
│   └── persistence (pri=15, caps=[persistence], deps=[config, workspace])
│       └── compaction (pri=16, caps=[compaction], deps=[config, persistence])
├── communication (pri=5, caps=[], deps=[])
│   ├── session (pri=50, caps=[], deps=[communication])
│   │   └── telegram (pri=30, caps=[communication], deps=[session])
│   └── loop (pri=50, caps=[loop], deps=[config, communication])
├── security (pri=10, caps=[security], deps=[config])
├── trust (pri=16, caps=[], deps=[config])
├── context (pri=18, caps=[], deps=[config])
├── skills (pri=19, caps=[tools], deps=[config], opt_deps=[workspace])
├── ppq (pri=20, caps=[llm], deps=[config])
├── ollama (pri=20, caps=[llm], deps=[config])
├── knowledge (pri=22, caps=[knowledge, tools], deps=[config])
├── filedrop (pri=24, caps=[communication], deps=[config])
├── nostr (pri=25, caps=[communication], deps=[config])
├── wallet (pri=25, caps=[wallet, tools], deps=[config])
├── pairing (pri=5, caps=[pairing], deps=[config], opt_deps=[communication])
├── tools (pri=30, caps=[tools], deps=[config])
├── web (pri=30, caps=[], deps=[config])
├── subagent (pri=32, caps=[subagent, tools], deps=[config])
├── cron (pri=40, caps=[cron, tools], deps=[config], opt_deps=[subagent, communication, filedrop])
│   └── heartbeat (pri=45, caps=[], deps=[cron])
```

**Key observations:**
- Maximum dependency depth: 4 (telegram → session → communication, or memory-files → memory → workspace → config)
- No existing cycles
- `communication` plugin has no dependencies (not even `config`) — it's a lightweight dispatcher
- Most plugins depend only on `config`; deeper chains are workspace-related and communication-related

---

## 7. Resolver Algorithm — Detailed Pseudocode

```python
def resolve(discovered, policy, enabled, disabled, provider, core_ids):
    # --- Phase 1: Determine enabled set ---
    if policy == "enable":
        enabled_set = set(discovered.keys())
        enabled_set -= set(disabled)
        # Remove non-selected LLM providers
        for pid, node in discovered.items():
            if "llm" in node.capabilities and pid != provider:
                enabled_set.discard(pid)
        reasons = {pid: "direct" for pid in enabled_set}
    else:  # policy == "disable"
        enabled_set = set(enabled)
        reasons = {pid: "direct" for pid in enabled_set}

    # Always add core
    for cid in core_ids:
        if cid in discovered:
            enabled_set.add(cid)
            reasons[cid] = "core"

    # Add selected provider
    if provider in discovered:
        enabled_set.add(provider)
        reasons[provider] = "core"

    # --- Phase 2: Resolve transitive dependencies ---
    queue = list(enabled_set)
    resolved = set(enabled_set)
    while queue:
        pid = queue.pop(0)
        node = discovered.get(pid)
        if node is None:
            raise PluginError(f"Plugin '{pid}' not found in discovered plugins")
        for dep in node.dependencies:
            if dep in set(disabled):
                raise PluginError(
                    f"Plugin '{pid}' requires '{dep}', which is in plugins.disabled.\n"
                    f"  Fix: Remove '{dep}' from disabled, or don't enable '{pid}'."
                )
            if dep not in discovered:
                raise PluginError(
                    f"Plugin '{pid}' requires '{dep}', which is not installed."
                )
            if dep not in resolved:
                resolved.add(dep)
                reasons[dep] = "transitive"
                queue.append(dep)

    # --- Phase 3: Cycle detection + topological sort ---
    # Kahn's algorithm on the resolved subset
    in_degree = {pid: 0 for pid in resolved}
    adj = {pid: [] for pid in resolved}
    for pid in resolved:
        for dep in discovered[pid].dependencies:
            if dep in resolved:
                adj[dep].append(pid)
                in_degree[pid] += 1

    # Use priority-based heap for stable tiebreaking
    import heapq
    queue = [(discovered[pid].priority, pid) for pid in resolved if in_degree[pid] == 0]
    heapq.heapify(queue)

    order = []
    while queue:
        pri, pid = heapq.heappop(queue)
        order.append(pid)
        for dependent in adj[pid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(queue, (discovered[dependent].priority, dependent))

    if len(order) != len(resolved):
        # Cycle exists — find it for error reporting
        remaining = resolved - set(order)
        cycle_path = _find_cycle(discovered, remaining)
        raise PluginError(f"Circular dependency detected: {' → '.join(cycle_path)}")

    # --- Build skipped dict ---
    skipped = {}
    for pid in discovered:
        if pid not in resolved:
            if pid in disabled:
                skipped[pid] = "disabled"
            elif "llm" in discovered[pid].capabilities and pid != provider:
                skipped[pid] = "provider-skip"
            else:
                skipped[pid] = "not-reachable"

    return ResolveResult(
        load_order=order,
        load_reasons=reasons,
        skipped=skipped,
        warnings=warnings,
    )


def _find_cycle(discovered, remaining):
    """DFS to find and report one cycle in remaining nodes."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {pid: WHITE for pid in remaining}
    path = []

    def dfs(pid):
        color[pid] = GRAY
        path.append(pid)
        for dep in discovered[pid].dependencies:
            if dep in remaining:
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    return path[cycle_start:] + [dep]
                if color[dep] == WHITE:
                    result = dfs(dep)
                    if result:
                        return result
        path.pop()
        color[pid] = BLACK
        return None

    for pid in remaining:
        if color[pid] == WHITE:
            result = dfs(pid)
            if result:
                return result
    return list(remaining)  # fallback
```

---

## 8. Changes to `init_plugins()`

Current `init_plugins()` flow:
```
discover → filter (flat) → register → configure → start
```

New flow:
```
discover → extract PluginNodes → resolve() → register (resolved only, in order) → configure → start
```

Key changes:

```python
async def init_plugins(plugins_dir: Path, config: dict = None) -> PluginRegistry:
    config = config or {}
    provider = config.get("provider", "ppq")
    plugins_config = config.get("plugins", {})

    # NEW: Parse policy
    policy = plugins_config.get("policy", "enable")
    enabled_list = plugins_config.get("enabled", [])
    disabled_list = plugins_config.get("disabled", [])
    external_packages = plugins_config.get("external", [])

    registry = get_registry()

    # Discover all plugin classes (unchanged)
    plugin_classes = discover_plugins(plugins_dir)
    if external_packages:
        plugin_classes.extend(load_external_plugins(external_packages))

    # NEW: Build PluginNode dict from discovered classes
    discovered = {}
    class_map = {}  # id → class
    for cls in plugin_classes:
        node = PluginNode(
            id=cls.meta.id,
            dependencies=cls.meta.dependencies,
            optional_dependencies=cls.meta.optional_dependencies,
            capabilities=cls.meta.capabilities,
            consumes=cls.meta.consumes,
            priority=cls.meta.priority,
        )
        discovered[cls.meta.id] = node
        class_map[cls.meta.id] = cls

    # NEW: Resolve
    core_ids = ["config", "logger"]
    result = resolve(discovered, policy, enabled_list, disabled_list, provider, core_ids)

    # Log diagnostics
    for pid in result.load_order:
        reason = result.load_reasons[pid]
        _early_log("info", "resolver", f"Loading: {pid} [{reason}]")
    for pid, reason in result.skipped.items():
        _early_log("info", "resolver", f"Skipped: {pid} [{reason}]")

    # Register in resolved order
    for pid in result.load_order:
        try:
            registry.register(class_map[pid])
        except PluginError as e:
            _early_log("error", "plugins", f"Failed to register: {e}")

    # Set load order directly (no re-resolution)
    registry._load_order = result.load_order

    # Configure and start
    registry.configure_all(config)
    await registry.start_all()
    return registry
```

### Changes to `registry.py`

1. **Remove `_resolve_load_order()`** — order comes from resolver
2. **Remove `_check_dependencies()`** — resolver handles this
3. **Modify `configure_all()`** — skip internal ordering, use pre-set `_load_order`

```python
def configure_all(self, config: dict) -> None:
    # _load_order already set by init_plugins from resolver
    # No need to call _resolve_load_order() or _check_dependencies()
    for plugin_id in self._load_order:
        plugin = self._plugins[plugin_id]
        try:
            plugin.configure(config)
        except Exception as e:
            _log("error", f"Failed to configure '{plugin_id}': {e}")
            raise PluginError(f"Configuration failed for '{plugin_id}': {e}")
```

---

## 9. Validation Checklist

### Requirements Coverage

| Requirement | Architecture Component | Status |
|------------|----------------------|--------|
| FR1: Load Policy Engine | `resolve()` Phase 1 | ✅ Covered |
| FR2: Transitive Deps | `resolve()` Phase 2 BFS | ✅ Covered |
| FR3: Conflict Detection | Phase 2 disabled check | ✅ Covered |
| FR4: Cycle Detection | Kahn's + `_find_cycle()` | ✅ Covered |
| FR5: Topological Order | Kahn's with priority heap | ✅ Covered |
| FR6: Capability-Based Deps | Provider selection in Phase 1 | ✅ MVP scope |
| FR7: Startup Diagnostics | `ResolveResult` + logging | ✅ Covered |
| NFR1: Performance | O(V+E) algorithm | ✅ Trivially met |
| NFR2: Backward Compat | Implicit `policy: enable` | ✅ Covered |
| NFR3: Error Quality | Config-referencing messages | ✅ Pattern enforced |
| NFR4: Testability | Pure function resolver | ✅ By design |

### Design Decision Compliance

| Decision | Architecture | Status |
|----------|-------------|--------|
| DD1: No roots | Enabled set = entry points | ✅ |
| DD2: Load policy | `policy` field parsed | ✅ |
| DD3: Transitive deps | BFS from enabled set | ✅ |
| DD4: Conflict = hard error | `PluginError` raised | ✅ |
| DD5: Backward compatible | Implicit `policy: enable` | ✅ |

### Scenario Walkthrough: Issue #227

**Config:** `policy: disable`, `enabled: [telegram]`, `provider: ppq`

**Resolution:**
1. Enabled set: `{telegram}` + core `{config, logger, ppq}`
2. Transitive: telegram → session → communication
3. Resolved: `{config, logger, ppq, communication, session, telegram}`
4. No `loop` plugin loaded → `agent.run()` enters headless mode (existing behavior)
5. **No crash.** ✅

### Scenario: Full Agent (Backward Compat)

**Config:** No `policy` key, `disabled: [ollama]`

**Resolution:**
1. Implicit `policy: enable` → all 29 plugins minus `ollama`
2. Transitive: no new additions (all already included)
3. Topological sort produces valid load order
4. **Identical behavior to current system** ✅

### Scenario: Conflict Detection

**Config:** `policy: disable`, `enabled: [heartbeat]`, `disabled: [cron]`

**Resolution:**
1. Enabled set: `{heartbeat}` + core
2. Transitive: heartbeat → cron → **cron is in disabled list!**
3. `PluginError: Plugin 'heartbeat' requires 'cron', which is in plugins.disabled.`
4. **Startup fails with actionable error** ✅

---

## 10. Implementation Guidance

### File Change Summary

| File | Action | Lines (est.) |
|------|--------|-------------|
| `cobot/plugins/resolver.py` | **CREATE** | ~150 |
| `cobot/plugins/__init__.py` | **MODIFY** | ~40 changed |
| `cobot/plugins/registry.py` | **MODIFY** | ~20 removed, ~5 added |
| `tests/test_resolver.py` | **CREATE** | ~200 |
| `tests/test_init_plugins.py` | **MODIFY** | ~30 added |

### Implementation Order

1. **Create `resolver.py`** with `PluginNode`, `ResolveResult`, `resolve()`, `_find_cycle()`
2. **Write `test_resolver.py`** — all unit tests (cycle, transitive, conflict, both policies, backward compat)
3. **Modify `__init__.py`** — refactor `init_plugins()` to use resolver
4. **Modify `registry.py`** — remove `_resolve_load_order()` and `_check_dependencies()`, add `set_load_order()`
5. **Update integration tests** — verify existing configs produce same plugin sets
6. **Audit plugin dependencies** — verify all 29 plugins have correct declarations

### Migration Safety

The resolver is called from `init_plugins()` only when the refactored code is in place. Since the default `policy: enable` with no disabled list produces all-plugins-loaded (same as current), the migration is zero-risk for existing deployments. The only new behavior is:
- Better load ordering (topological vs priority-only)
- Dependency validation (catches issues that currently pass silently)
- New `policy: disable` mode (opt-in)

---

*Architecture document complete. Ready for implementation.*
