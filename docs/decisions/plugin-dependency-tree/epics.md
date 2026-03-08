# Epics & Stories: Cobot Plugin Dependency Tree Resolution

---

## Requirements Extraction

### Functional Requirements

- **FR1: Load Policy Engine** — Add `policy` field (`enable`/`disable`) to plugins config; determine initial plugin set based on policy
- **FR2: Transitive Dependency Resolution** — BFS/DFS from enabled set to collect all transitive deps; handle chains, diamonds, self-refs
- **FR3: Conflict Detection** — Resolved plugin requiring disabled dep → hard error before any plugin starts; actionable error messages with full chain
- **FR4: Cycle Detection** — DFS-based cycle detection during topological sort; hard error with full cycle path
- **FR5: Topological Load Ordering** — Replace priority-based `_resolve_load_order()` with topological sort; priority as tiebreaker within same level
- **FR6: Capability-Based Dependencies** — Map capability requirements to concrete providers (MVP: LLM provider selection)
- **FR7: Startup Diagnostics** — Log resolved set with load reasons (`direct`/`transitive`/`core`); log skipped plugins with reasons

### Non-Functional Requirements

- **NFR1:** Resolution <50ms for 50 plugins
- **NFR2:** Full backward compatibility — no `policy` key = identical behavior to current
- **NFR3:** Actionable error messages referencing config keys, not code internals
- **NFR4:** Resolver testable as pure functions without plugin instantiation

### Additional Requirements

- Core plugins (`config`, `logger`, selected LLM provider) always load
- External plugins via `load_external_plugins()` participate in resolution
- Logging before logger plugin available via `_early_log()` pattern



---

## Epic List

### Epic 1: Dependency Resolver Engine
Create the pure-function resolver module that computes what plugins to load, in what order, given a policy and plugin metadata.
**FRs covered:** FR2, FR4, FR5

### Epic 2: Load Policy & Config Integration
Users can set `policy: enable` or `policy: disable` in `cobot.yml` with full backward compatibility. Refactor `init_plugins()` to use the resolver.
**FRs covered:** FR1, FR3, FR6

### Epic 3: Registry Refactor & Topological Ordering
The plugin registry uses resolver-provided load order instead of its own priority-based sort.
**FRs covered:** FR5 (integration), FR3 (integration)

### Epic 4: Startup Diagnostics & Observability
Operators and maintainers see exactly what loaded, why, and what was skipped at startup.
**FRs covered:** FR7

### Epic 5: Testing & Dependency Audit
Comprehensive test suite and audit of all 29 existing plugin dependency declarations.
**FRs covered:** All FRs (validation), NFR1-NFR4

### FR Coverage Map

| FR | Epic | Description |
|----|------|-------------|
| FR1 | Epic 2 | Load policy parsing and initial set determination |
| FR2 | Epic 1 | Transitive dependency BFS in resolver |
| FR3 | Epic 2, Epic 3 | Conflict detection in resolver, integrated via init_plugins |
| FR4 | Epic 1 | Cycle detection via DFS in resolver |
| FR5 | Epic 1, Epic 3 | Topological sort in resolver, replaces registry sort |
| FR6 | Epic 2 | Capability-based deps (LLM provider selection) |
| FR7 | Epic 4 | Startup diagnostics logging |
| NFR1-4 | Epic 5 | Validated through test suite |

---

## Epic 1: Dependency Resolver Engine

**Goal:** Create `cobot/plugins/resolver.py` — a pure-function module that resolves plugin dependency trees, detects cycles, and produces topological load order.

### Story 1.1: PluginNode and ResolveResult Data Structures

As a plugin system developer,
I want lightweight data structures representing plugin metadata and resolution output,
So that the resolver can operate on simple data without importing actual plugin classes.

**Acceptance Criteria:**

**Given** the resolver module exists at `cobot/plugins/resolver.py`
**When** I import `PluginNode` and `ResolveResult`
**Then** `PluginNode` is a dataclass with fields: `id: str`, `dependencies: list[str]`, `optional_dependencies: list[str]`, `capabilities: list[str]`, `consumes: list[str]`, `priority: int`
**And** `ResolveResult` is a dataclass with fields: `load_order: list[str]`, `load_reasons: dict[str, str]`, `skipped: dict[str, str]`, `warnings: list[str]`
**And** both are importable without any plugin system side effects

**Technical Notes:**
- Mirror field names from existing `PluginMeta` in `base.py`
- `load_reasons` values: `"direct"`, `"transitive"`, `"core"`
- `skipped` values: `"disabled"`, `"not-reachable"`, `"provider-skip"`

### Story 1.2: Transitive Dependency Resolution

As a plugin system developer,
I want a function that resolves transitive dependencies from an enabled set,
So that enabling plugin A automatically includes all plugins A depends on (recursively).

**Acceptance Criteria:**

**Given** a discovered plugin set: `heartbeat → cron → config`
**When** I call the resolver with `enabled=["heartbeat"]`
**Then** the resolved set includes `heartbeat`, `cron`, and `config`

**Given** a diamond dependency: `A → B → D`, `A → C → D`
**When** I call the resolver with `enabled=["A"]`
**Then** D appears exactly once in the resolved set

**Given** plugin `X` depends on `Y` which is not in the discovered set
**When** I call the resolver with `enabled=["X"]`
**Then** a `PluginError` is raised: `"Plugin 'X' requires 'Y', which is not installed."`

**Given** plugin `X` depends on `Y` which is in the `disabled` list
**When** I call the resolver with `enabled=["X"]`, `disabled=["Y"]`
**Then** a `PluginError` is raised: `"Plugin 'X' requires 'Y', which is in plugins.disabled."`
**And** the error includes a fix suggestion

**Technical Notes:**
- BFS from enabled set, tracking visited nodes
- Dependencies flow downward only: loading B because A needs it does NOT auto-load A's dependents
- Implementation: `_resolve_transitive(enabled_set, discovered, disabled) → resolved_set`

### Story 1.3: Cycle Detection

As a plugin system developer,
I want the resolver to detect circular dependencies and report them clearly,
So that cycles are caught at resolution time, not as infinite loops at runtime.

**Acceptance Criteria:**

**Given** plugins where `A → B → C → A` (cycle)
**When** I call the resolver
**Then** a `PluginError` is raised with message containing `"Circular dependency detected: A → B → C → A"`

**Given** plugins where `A → A` (self-reference)
**When** I call the resolver
**Then** a `PluginError` is raised with message containing `"Circular dependency detected: A → A"`

**Given** a valid DAG with no cycles (all 29 current Cobot plugins)
**When** I call the resolver
**Then** no cycle error is raised

**Technical Notes:**
- DFS with 3-color marking (WHITE/GRAY/BLACK)
- `_find_cycle(discovered, remaining_nodes) → list[str]` returns the cycle path
- Cycle detection happens as part of Kahn's algorithm (remaining nodes after sort = cycle)

### Story 1.4: Topological Sort with Priority Tiebreaker

As a plugin system developer,
I want plugins sorted in dependency order with priority as tiebreaker for unrelated plugins,
So that every plugin's dependencies are loaded before it, and existing priority ordering is preserved where possible.

**Acceptance Criteria:**

**Given** plugins: `config(pri=1)`, `workspace(pri=5, deps=[config])`, `memory(pri=12, deps=[workspace])`
**When** I resolve and sort
**Then** load order is `[config, workspace, memory]`

**Given** unrelated plugins `cli(pri=5)` and `security(pri=10)`, both depending only on `config(pri=1)`
**When** I resolve and sort
**Then** `config` comes first, `cli` before `security` (priority tiebreaker)

**Given** the full set of 29 current Cobot plugins
**When** I resolve with `policy: enable`
**Then** every plugin appears after all its declared dependencies in the load order

**Technical Notes:**
- Kahn's algorithm with a min-heap keyed by `(priority, plugin_id)` for stable ordering
- Replaces existing `_resolve_load_order()` which only sorts by priority
- Resolves the `TODO: Topological sort for dependencies` comment in `registry.py`

### Story 1.5: Top-Level `resolve()` Function

As a plugin system developer,
I want a single entry point function that orchestrates all resolution steps,
So that callers can get a complete `ResolveResult` with one call.

**Acceptance Criteria:**

**Given** a full discovered plugin set, policy, enabled/disabled lists, provider, and core IDs
**When** I call `resolve(discovered, policy, enabled, disabled, provider, core_ids)`
**Then** it returns a `ResolveResult` with correct `load_order`, `load_reasons`, `skipped`, and `warnings`

**Given** `policy="enable"`, no disabled list
**When** I call `resolve()`
**Then** all discovered plugins are in `load_order` (minus non-selected LLM providers)
**And** all load reasons are `"direct"` (or `"core"` for core plugins)

**Given** `policy="disable"`, `enabled=["telegram"]`, `provider="ppq"`, `core_ids=["config", "logger"]`
**When** I call `resolve()`
**Then** `load_order` contains exactly: `config`, `logger`, `ppq`, `communication`, `session`, `telegram`
**And** load reasons: config=core, logger=core, ppq=core, communication=transitive, session=transitive, telegram=direct
**And** all other plugins appear in `skipped` with appropriate reasons

**Technical Notes:**
- Orchestrates: Phase 1 (determine enabled set) → Phase 2 (transitive resolution) → Phase 3 (cycle detection + topological sort)
- Pure function, no side effects, no logging (logging done by caller)

---

## Epic 2: Load Policy & Config Integration

**Goal:** Integrate the resolver into `init_plugins()` so that `policy: enable`/`disable` in `cobot.yml` drives plugin loading, with full backward compatibility.

### Story 2.1: Parse Load Policy from Config

As a Cobot operator,
I want to set `policy: enable` or `policy: disable` in my `cobot.yml`,
So that I can control whether the system loads all plugins by default or only those I specify.

**Acceptance Criteria:**

**Given** a `cobot.yml` with `plugins.policy: "disable"`
**When** `init_plugins()` parses the config
**Then** the policy is set to `"disable"`

**Given** a `cobot.yml` without a `policy` key in `plugins`
**When** `init_plugins()` parses the config
**Then** the policy defaults to `"enable"` (backward compatible)

**Given** a `cobot.yml` with `plugins.policy: "invalid_value"`
**When** `init_plugins()` parses the config
**Then** a `PluginError` is raised: `"Invalid policy: must be 'enable' or 'disable'"`

**Technical Notes:**
- Parse from `config.get("plugins", {}).get("policy", "enable")`
- Validate before calling resolver

### Story 2.2: Config Validation Rules

As a Cobot operator,
I want clear warnings or errors when my plugin config is unusual or contradictory,
So that I avoid subtle misconfiguration.

**Acceptance Criteria:**

**Given** `policy: enable` + `enabled` list present
**When** config is validated
**Then** a warning is logged: `"In enable-all mode, 'enabled' has no additional effect"`

**Given** `policy: disable` + `disabled` list present
**When** config is validated
**Then** a `PluginError` is raised: `"Cannot use 'disabled' with policy: disable"`

**Given** `policy: disable` + no `enabled` list
**When** config is validated
**Then** a warning is logged: `"Only core plugins will load"`

**Technical Notes:**
- Validation happens in `init_plugins()` before calling `resolve()`
- Warnings via `_early_log("warn", ...)`; errors raise `PluginError`

### Story 2.3: Build PluginNode Dict from Discovered Classes

As a plugin system developer,
I want `init_plugins()` to extract `PluginNode` objects from discovered plugin classes,
So that the resolver receives lightweight data without needing plugin instantiation.

**Acceptance Criteria:**

**Given** `discover_plugins()` returns a list of plugin classes
**When** `init_plugins()` builds the PluginNode dict
**Then** each class's `meta` fields (id, dependencies, optional_dependencies, capabilities, consumes, priority) are mapped to a `PluginNode`
**And** a `class_map: dict[str, type[Plugin]]` is built for later registration
**And** external plugins from `load_external_plugins()` are included in both dicts

**Technical Notes:**
- Iterate `plugin_classes`, read `cls.meta.*` fields, construct `PluginNode` per plugin
- Keep `class_map` for post-resolution registration

### Story 2.4: Replace Flat Filtering with Resolver Call

As a Cobot operator,
I want `init_plugins()` to use the dependency resolver instead of flat list filtering,
So that my config drives intelligent dependency-aware plugin loading.

**Acceptance Criteria:**

**Given** `policy: disable`, `enabled: [telegram]`, `provider: ppq`
**When** `init_plugins()` runs
**Then** only `config`, `logger`, `ppq`, `communication`, `session`, `telegram` are registered (in dependency order)
**And** no other plugins are registered or instantiated

**Given** `policy: enable`, `disabled: [ollama, nostr]`
**When** `init_plugins()` runs
**Then** all plugins except `ollama` and `nostr` are registered
**And** if any remaining plugin depends on `ollama` or `nostr`, startup fails with `PluginError`

**Given** no `policy` key, `enabled: [telegram, web, loop]` (existing config format)
**When** `init_plugins()` runs
**Then** behavior is identical to current: only listed plugins + core load

**Technical Notes:**
- Remove the existing flat filtering loop in `init_plugins()`
- Call `resolve()` then register only `result.load_order` plugins via `class_map`
- Set `registry._load_order = result.load_order` directly

### Story 2.5: LLM Provider Selection in Resolver

As a Cobot operator,
I want only my configured LLM provider to load, regardless of which providers are installed,
So that `provider: ppq` loads PPQ and skips Ollama (and vice versa).

**Acceptance Criteria:**

**Given** `provider: ppq` and both `ppq` and `ollama` are discovered
**When** the resolver runs with `policy: enable`
**Then** `ppq` is in `load_order` and `ollama` is in `skipped` with reason `"provider-skip"`

**Given** `provider: ppq` and `ppq` is NOT discovered
**When** the resolver runs
**Then** a `PluginError` is raised: `"Configured LLM provider 'ppq' not found"`

**Technical Notes:**
- In Phase 1, filter out LLM providers whose ID doesn't match `provider` config
- Selected provider is added to core set (always loads)

---

## Epic 3: Registry Refactor & Topological Ordering

**Goal:** Modify `PluginRegistry` to accept pre-computed load order from the resolver, removing its internal priority-based sorting and post-hoc dependency checking.

### Story 3.1: Remove `_resolve_load_order()` from Registry

As a plugin system developer,
I want to remove the priority-based `_resolve_load_order()` method,
So that load ordering is solely handled by the resolver's topological sort.

**Acceptance Criteria:**

**Given** the registry receives `_load_order` set directly by `init_plugins()`
**When** `configure_all()` is called
**Then** it does NOT call `_resolve_load_order()` — the method no longer exists
**And** it uses the pre-set `_load_order` directly

**Given** the `TODO: Topological sort for dependencies` comment in `registry.py`
**When** this story is complete
**Then** the TODO is resolved (topological sort lives in `resolver.py`)

**Technical Notes:**
- Delete `_resolve_load_order()` method entirely
- `configure_all()` currently calls `self._load_order = self._resolve_load_order()` — remove that line
- `_load_order` is set by `init_plugins()` before `configure_all()` is called

### Story 3.2: Remove `_check_dependencies()` from Registry

As a plugin system developer,
I want to remove the post-registration `_check_dependencies()` check,
So that dependency validation happens in the resolver before registration (fail-fast).

**Acceptance Criteria:**

**Given** the resolver has already validated all dependencies during resolution
**When** `configure_all()` is called
**Then** it does NOT call `_check_dependencies()` — the method no longer exists
**And** all dependency errors have already been caught by the resolver

**Technical Notes:**
- Delete `_check_dependencies()` method entirely
- `configure_all()` currently calls `self._check_dependencies()` — remove that line
- The resolver's conflict detection (Story 1.2) fully subsumes this functionality

### Story 3.3: Ensure Registry Lifecycle Uses Resolver Order

As a plugin system developer,
I want `start_all()` and `stop_all()` to use the resolver-provided order,
So that plugins start in dependency order and stop in reverse dependency order.

**Acceptance Criteria:**

**Given** resolver produces `load_order = [config, logger, ppq, communication, session, telegram]`
**When** `start_all()` runs
**Then** plugins start in exactly that order

**When** `stop_all()` runs
**Then** plugins stop in reverse order: `[telegram, session, communication, ppq, logger, config]`

**Technical Notes:**
- `start_all()` already iterates `self._load_order` — no change needed
- `stop_all()` already uses `reversed(self._load_order)` — no change needed
- This story is primarily a verification/test story ensuring the integration works end-to-end

---

## Epic 4: Startup Diagnostics & Observability

**Goal:** Log the resolved dependency tree at startup so operators and maintainers can see exactly what loaded and why.

### Story 4.1: Log Resolved Plugin Set with Load Reasons

As a Cobot operator,
I want to see which plugins loaded and why at startup,
So that I can verify my configuration is working as intended.

**Acceptance Criteria:**

**Given** the resolver returns a `ResolveResult`
**When** `init_plugins()` processes the result
**Then** each loaded plugin is logged via `_early_log("info", "resolver", ...)` with format: `"Loading: {plugin_id} [{reason}]"`
**And** reason is one of: `direct`, `transitive`, `core`

**Example output:**
```
[I] [resolver    ] Loading: config [core]
[I] [resolver    ] Loading: logger [core]
[I] [resolver    ] Loading: ppq [core]
[I] [resolver    ] Loading: communication [transitive]
[I] [resolver    ] Loading: session [transitive]
[I] [resolver    ] Loading: telegram [direct]
```

**Technical Notes:**
- Iterate `result.load_order` and `result.load_reasons` in `init_plugins()`
- Uses existing `_early_log()` since this runs before logger plugin starts

### Story 4.2: Log Skipped Plugins with Reasons

As a Cobot operator,
I want to see which plugins were skipped and why,
So that I can identify if something was unexpectedly excluded.

**Acceptance Criteria:**

**Given** the resolver returns skipped plugins in `ResolveResult.skipped`
**When** `init_plugins()` processes the result
**Then** each skipped plugin is logged with format: `"Skipped: {plugin_id} [{reason}]"`
**And** reason is one of: `disabled`, `not-reachable`, `provider-skip`

**Given** `policy: disable` with `enabled: [telegram]`
**When** startup completes
**Then** plugins like `nostr`, `heartbeat`, `cron`, `web` appear as `[not-reachable]`
**And** `ollama` appears as `[provider-skip]`

**Technical Notes:**
- Iterate `result.skipped` in `init_plugins()`
- Log at "info" level — these are expected, not errors

### Story 4.3: Log Resolved Policy Summary

As a Cobot operator,
I want a summary line showing the active policy and total plugin counts,
So that I can quickly see the resolution outcome.

**Acceptance Criteria:**

**Given** the resolver completes successfully
**When** `init_plugins()` logs diagnostics
**Then** a summary line is logged: `"Resolved {N} plugins (policy: {policy}), skipped {M}"`

**Example:** `"[I] [resolver    ] Resolved 6 plugins (policy: disable), skipped 23"`

**Technical Notes:**
- `len(result.load_order)` for loaded count, `len(result.skipped)` for skipped count
- Log before individual plugin lines for quick overview

---

## Epic 5: Testing & Dependency Audit

**Goal:** Comprehensive test coverage for the resolver and audit of all existing plugin dependency declarations.

### Story 5.1: Unit Tests — Core Resolution Scenarios

As a plugin system developer,
I want unit tests covering all standard resolution scenarios,
So that the resolver is proven correct for normal operation.

**Acceptance Criteria:**

**Given** `tests/test_resolver.py` exists
**Then** it contains tests for:
- Empty resolve: `policy=disable`, `enabled=[]` → only core plugins
- Single plugin, no deps: `policy=disable`, `enabled=[web]` → web + core
- Transitive chain: `enabled=[heartbeat]` → heartbeat, cron, config + core
- Diamond dependency: A→B→D, A→C→D → D loaded once
- Policy enable + disabled: `policy=enable`, `disabled=[nostr]` → all except nostr
- Provider selection: `provider=ppq` → ppq loads, ollama skipped
- Backward compat: no policy key → same as `policy=enable`
**And** all tests use `PluginNode` directly (no actual plugin imports)

**Technical Notes:**
- ~100 lines of test code
- Use pytest parametrize where appropriate
- Each test constructs a `discovered` dict with `PluginNode` objects

### Story 5.2: Unit Tests — Error Scenarios

As a plugin system developer,
I want unit tests covering all error paths,
So that conflict detection, cycle detection, and missing plugins are verified.

**Acceptance Criteria:**

**Given** `tests/test_resolver.py`
**Then** it contains tests for:
- Cycle detection: A→B→A → `PluginError` with cycle path
- Self-reference: A→A → `PluginError`
- Conflict: `enabled=[heartbeat]`, `disabled=[cron]` → `PluginError` naming heartbeat and cron
- Missing plugin: `enabled=[nonexistent]` → `PluginError`
- Missing dependency: A depends on B, B not discovered → `PluginError`
- Invalid policy value → `PluginError`
**And** error messages are verified to contain actionable information (plugin names, chain paths, fix suggestions)

**Technical Notes:**
- Use `pytest.raises(PluginError, match=...)` for message verification
- Test error messages include config key references (e.g., "plugins.disabled")

### Story 5.3: Integration Tests — Full init_plugins Flow

As a plugin system developer,
I want integration tests verifying that `init_plugins()` uses the resolver correctly,
So that the end-to-end flow from config to running plugins is validated.

**Acceptance Criteria:**

**Given** `tests/test_init_plugins.py` (modify existing if present)
**Then** it contains tests for:
- `policy: disable` + `enabled: [telegram]` → exactly the right plugins registered and started
- `policy: enable` + `disabled: [ollama]` → all plugins except ollama registered
- No policy key → identical behavior to current (regression test)
- Conflict scenario → startup fails with `PluginError` before any plugin starts
**And** existing tests still pass

**Technical Notes:**
- May need mocking of `discover_plugins()` to control test data
- Verify `registry._load_order` matches expected topological order

### Story 5.4: Dependency Audit of All 29 Plugins

As a Cobot maintainer,
I want all 29 existing plugin `PluginMeta.dependencies` declarations audited against actual usage,
So that the resolver works correctly with real plugin data.

**Acceptance Criteria:**

**Given** all 29 plugin directories in `cobot/plugins/`
**When** each plugin's `PluginMeta` is reviewed
**Then** a report documents: plugin ID, declared deps, actual deps (from imports/usage), discrepancies
**And** any missing declarations are added to the plugin's `PluginMeta`
**And** the full 29-plugin graph resolves without errors in both `policy: enable` and `policy: disable` modes

**Technical Notes:**
- Key plugins to verify: `session` (deps on `communication`), `telegram` (deps on `session`), `heartbeat` (deps on `cron`), `memory-files` (deps on `workspace` and `memory`)
- Check for implicit deps via `registry.get()` or `registry.get_by_capability()` calls in plugin code
- Add a test that resolves the actual full plugin set



---

## Final Validation

### FR Coverage Validation ✅

| FR | Covered By | Status |
|----|-----------|--------|
| FR1: Load Policy Engine | Story 2.1 (parse policy), Story 2.2 (validation), Story 2.4 (integration) | ✅ |
| FR2: Transitive Deps | Story 1.2 (BFS resolution), Story 1.5 (top-level resolve) | ✅ |
| FR3: Conflict Detection | Story 1.2 (disabled dep check), Story 2.4 (integration in init_plugins) | ✅ |
| FR4: Cycle Detection | Story 1.3 (DFS cycle detection) | ✅ |
| FR5: Topological Order | Story 1.4 (Kahn's algorithm), Story 3.1 (registry integration) | ✅ |
| FR6: Capability Deps | Story 2.5 (LLM provider selection) | ✅ |
| FR7: Startup Diagnostics | Stories 4.1, 4.2, 4.3 (load reasons, skipped, summary) | ✅ |
| NFR1: Performance | Story 1.4 (O(V+E) algorithm), Story 5.1 (benchmarkable tests) | ✅ |
| NFR2: Backward Compat | Story 2.1 (default policy=enable), Story 2.4 (existing config behavior), Story 5.3 (regression tests) | ✅ |
| NFR3: Error Quality | Story 1.2, 1.3, 5.2 (actionable messages with config refs) | ✅ |
| NFR4: Testability | Story 1.1 (pure data structures), Stories 5.1-5.3 (comprehensive tests) | ✅ |

### Architecture Compliance ✅

- No starter template needed (brownfield enhancement)
- New file: `cobot/plugins/resolver.py` (Epic 1)
- Modified: `cobot/plugins/__init__.py` (Epic 2), `cobot/plugins/registry.py` (Epic 3)
- New test: `tests/test_resolver.py` (Epic 5)
- No database/entity concerns (plugin system, not data layer)

### Story Dependency Validation ✅

**Epic 1:** Stories 1.1→1.2→1.3→1.4→1.5 — each builds on previous. Data structures first, then algorithms, then orchestration.
**Epic 2:** Stories 2.1→2.2→2.3→2.4→2.5 — config parsing, validation, data extraction, integration, provider selection. Each independently completable in sequence.
**Epic 3:** Stories 3.1→3.2→3.3 — remove old methods, verify lifecycle. Depends on Epic 1+2 being complete. Each story independently completable.
**Epic 4:** Stories 4.1→4.2→4.3 — logging additions. Depends on Epic 2 integration. Each story independently completable.
**Epic 5:** Stories 5.1→5.2→5.3→5.4 — unit tests, error tests, integration tests, audit. Can start after Epic 1.

### Epic Independence ✅

- **Epic 1** is standalone: produces `resolver.py` testable in isolation
- **Epic 2** depends on Epic 1: integrates resolver into `init_plugins()`
- **Epic 3** depends on Epic 2: cleans up registry after integration
- **Epic 4** depends on Epic 2: adds logging to the integration point
- **Epic 5** can start after Epic 1, full suite after Epic 3

### Summary

- **5 Epics**, **18 Stories**
- All 7 FRs and 4 NFRs covered
- No forward dependencies within epics
- All stories sized for single dev agent completion
- Ready for implementation
