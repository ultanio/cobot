# Plugin Design Guide

This is the authoritative reference for designing Cobot plugins. It codifies patterns discovered during development and provides principles that reviewers can check PRs against.

**Audience:** Plugin authors (human and AI), code reviewers.

## 1. PluginMeta Vocabulary

Every plugin declares a `PluginMeta` dataclass ([`cobot/plugins/base.py`, line 22](../cobot/plugins/base.py#L22)). Here is the complete field reference:

| Field | Type | Default | Meaning | Use when… | Example |
|-------|------|---------|---------|-----------|---------|
| `id` | `str` | *(required)* | Unique plugin identifier | Always — every plugin needs one | `"knowledge"` |
| `version` | `str` | *(required)* | Semver string | Always | `"1.0.0"` |
| `capabilities` | `list[str]` | `[]` | "I provide X" — services others can discover | Your plugin offers a service | `["wallet", "tools"]` |
| `dependencies` | `list[str]` | `[]` | "I require plugin X" (hard) | Plugin won't function without it | `["config"]` |
| `optional_dependencies` | `list[str]` | `[]` | "I can use plugin X if loaded" | Enhanced behavior if present, works without | `["llm"]` |
| `consumes` | `list[str]` | `[]` | "I aggregate from capability group X" | You call `all_with_capability()` | `["tools", "llm"]` |
| `priority` | `int` | `50` | Load order (lower = earlier) | Control startup sequencing | `22` |
| `extension_points` | `list[str]` | `[]` | "I define this contract" | Others should hook into your lifecycle | `["loop.before_llm"]` |
| `implements` | `dict[str, str]` | `{}` | "I fulfill this extension point" | You handle another plugin's hook | `{"context.system_prompt": "get_soul"}` |
| `secrets` | — | — | Declared secret requirements | ⏳ **Pending [#50](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/50)** — not yet in PluginMeta | — |

### Priority Bands

| Range | Role | Examples |
|-------|------|---------|
| 1–9 | Foundation | config |
| 10–19 | Core services | persistence, logger |
| 20–29 | Service plugins | knowledge (22), wallet (25) |
| 30–49 | Aggregators | tools (30) |
| 50+ | Orchestration | loop (50) |

### Graph Representation

| Field | Graph edge |
|-------|-----------|
| `capabilities` | Node attribute + edge to capability hub |
| `dependencies` | Solid directed edge → required plugin |
| `optional_dependencies` | Dashed directed edge → optional plugin |
| `consumes` | Edge from capability hub |
| `implements` | Green edge → extension point |
| `extension_points` | Node attribute (defines contract) |

## 2. Design Principles

### Principle 1: Own Your Tools

If your plugin provides tools to the LLM agent, implement `ToolProvider` ([`cobot/plugins/interfaces.py`, line 202](../cobot/plugins/interfaces.py#L202)) and declare `capabilities: ["tools"]`. Never add your tool definitions to another plugin's file.

✅ **Correct** — `KnowledgePlugin` implements `ToolProvider` directly and owns its tool definitions and execution:
```python
# cobot/plugins/knowledge/plugin.py, line 100
class KnowledgePlugin(Plugin, ToolProvider):
```

✅ **Correct** — `WalletPlugin` implements both `WalletProvider` and `ToolProvider`:
```python
# cobot/plugins/wallet/plugin.py, line 54
class WalletPlugin(Plugin, WalletProvider, ToolProvider):
```

❌ **Anti-pattern** — One plugin hardcoding tool definitions for another plugin (see [Anti-Patterns](#anti-pattern-god-object-tool-registry)).

### Principle 2: Declare All Coupling

If your plugin calls `get_by_capability()` ([`registry.py`, line 100](../cobot/plugins/registry.py#L100)) or `all_with_capability()` ([`registry.py`, line 118](../cobot/plugins/registry.py#L118)), declare it in PluginMeta via `consumes` or `optional_dependencies`. **If it's not in the graph, it's not in the architecture.**

✅ **Correct** — `LoopPlugin` declares what it aggregates:
```python
# cobot/plugins/loop/plugin.py, line 94
meta = PluginMeta(
    ...
    consumes=["llm", "tools"],   # line 99
```

✅ **Correct** — `ToolsPlugin` declares its aggregation role:
```python
# cobot/plugins/tools/plugin.py, line 101
meta = PluginMeta(
    ...
    consumes=["tools"],          # line 106
```

### Principle 3: Adding a Plugin Never Requires Editing Another Plugin

New `ToolProvider` plugins appear automatically via capability discovery. New extension point implementations wire in via `implements`. If adding your plugin requires editing an existing one, the architecture is wrong.

The `ToolsPlugin.get_definitions()` method ([`cobot/plugins/tools/plugin.py`, line 153](../cobot/plugins/tools/plugin.py#L153)) demonstrates this — it aggregates from all `"tools"` capability providers automatically:

```python
# cobot/plugins/tools/plugin.py, line 160
# Aggregate from other ToolProvider plugins
if self._registry:
    for plugin in self._registry.all_with_capability("tools"):
        if plugin.meta.id == self.meta.id:
            continue  # Skip self
```

### Principle 4: Hard Deps for Requirements, Capabilities for Discovery

- `dependencies: ["config"]` — plugin won't start without config
- `consumes: ["tools"]` — plugin aggregates from whoever provides `"tools"`
- `get_by_capability("llm")` — get whichever LLM provider is active (swappable singleton)
- `all_with_capability("tools")` — collect from all ToolProviders (registry/aggregation pattern)

**Decision tree:**

```
Will your plugin crash without it?
├── YES → dependencies (hard requirement)
└── NO
    ├── Do you need ALL plugins with capability?
    │   └── YES → consumes + all_with_capability()
    └── Do you need ONE plugin with capability?
        ├── Required → optional_dependencies + get_by_capability()
        └── Nice to have → just get_by_capability() with None handling
```

### Principle 5: No Secrets from Environment

Plugins should never read credentials directly via `os.environ`. Use the declared `secrets` field once [#50](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/50) lands. Until then, receive configuration via `configure()` and document any required environment variables.

## 3. Patterns Catalog

### Pattern: ToolProvider

**When:** Your plugin wants to expose actions to the LLM agent.

**How:**
1. Implement `ToolProvider` from [`cobot/plugins/interfaces.py`, line 202](../cobot/plugins/interfaces.py#L202)
2. Add `"tools"` to `capabilities`
3. Define `get_definitions()` returning OpenAI-format tool defs
4. Implement `execute(tool_name, args)` to dispatch calls

**Example:** `KnowledgePlugin` ([`cobot/plugins/knowledge/plugin.py`, line 100](../cobot/plugins/knowledge/plugin.py#L100)) — provides `knowledge_search`, `knowledge_add`, and `knowledge_stats` tools.

**Why it works:** The tools plugin automatically discovers all `ToolProvider` plugins and aggregates their definitions. No registration step needed.

---

### Pattern: Swappable Provider

**When:** Multiple plugins can fulfill the same role (e.g., different LLM backends).

**How:**
1. Both plugins declare the same capability (e.g., `capabilities: ["llm"]`)
2. Consumer uses `get_by_capability("llm")` to get whichever is active
3. Both implement the same interface (e.g., `LLMProvider`)

**Example:** `ppq` and `ollama` both declare `capabilities: ["llm"]` and implement `LLMProvider` ([`cobot/plugins/interfaces.py`, line 37](../cobot/plugins/interfaces.py#L37)). The `LoopPlugin` doesn't know or care which one is loaded.

**Why it works:** Priority ordering determines which provider wins when only one is needed. The consumer is decoupled from the concrete implementation.

---

### Pattern: Extension Point Hook

**When:** Your plugin defines a lifecycle event others should participate in.

**How:**
1. Define hooks in `extension_points` list
2. Call them via `call_extension()` or `call_extension_chain()` ([`cobot/plugins/base.py`, line 105](../cobot/plugins/base.py#L105))
3. Other plugins declare handlers in `implements` dict

**Example:** `LoopPlugin` ([`cobot/plugins/loop/plugin.py`, line 94](../cobot/plugins/loop/plugin.py#L94)) defines 12 extension points (`loop.on_message`, `loop.before_llm`, etc.). Other plugins implement them:

```python
# Any plugin can hook into the loop
meta = PluginMeta(
    id="my-hook",
    implements={"loop.before_llm": "my_before_llm_handler"},
)
```

**Chain vs Collect:**
- `call_extension_chain()` — each handler receives and returns `ctx`; supports `ctx["abort"]` to stop the chain
- `call_extension()` — collects non-None results into a list

---

### Pattern: Capability Aggregation

**When:** Your plugin collects from all providers of a capability.

**How:**
1. Use `all_with_capability("X")` to get all providers
2. Declare `consumes: ["X"]` in PluginMeta so the dependency is visible in the graph

**Example:** `LoopPlugin` ([`cobot/plugins/loop/plugin.py`, line 99](../cobot/plugins/loop/plugin.py#L99)) declares `consumes: ["llm", "tools"]` and uses `AggregatedToolProvider` ([line 23](../cobot/plugins/loop/plugin.py#L23)) to merge all tool providers into one unified interface.

**Why it works:** New tool providers are automatically included. The loop plugin never needs to be edited when a new tool-providing plugin is added.

## 4. Anti-Patterns

### Anti-Pattern: God Object Tool Registry

**Symptom:** One plugin hardcodes tool definitions for other plugins, becoming a bottleneck that must be edited whenever a new tool is added.

**Fix:** Each plugin owns its tools via `ToolProvider`. The tools plugin aggregates automatically via `all_with_capability("tools")` ([`cobot/plugins/tools/plugin.py`, line 160](../cobot/plugins/tools/plugin.py#L160)).

**Ref:** [#58](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/58) — wallet tool definitions being moved from tools plugin to wallet plugin.

---

### Anti-Pattern: Hidden Service Locator

**Symptom:** A plugin calls `get_by_capability()` or `all_with_capability()` at runtime without declaring the relationship in PluginMeta. The dependency graph is incomplete — `cobot plugins inspect` won't show the edge.

**Fix:** Add `consumes` (for aggregation) or `optional_dependencies` (for optional single-provider lookup) to PluginMeta.

**Ref:** [#57](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/57) — discovered 10 plugins with invisible coupling.

---

### Anti-Pattern: Environment Grab Bag

**Symptom:** Plugin reads secrets via `os.environ.copy()` or `os.environ.get("SECRET")`, passing the entire environment to subprocesses.

**Example:** `WalletPlugin` ([`cobot/plugins/wallet/plugin.py`, line 83](../cobot/plugins/wallet/plugin.py#L83)):
```python
self._env = os.environ.copy()
```

**Fix:** Declare secrets in PluginMeta (pending [#50](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/50)), receive them via config injection, and pass only required variables to subprocesses.

## 5. Reviewer Checklist

For every plugin PR, reviewers should verify:

- [ ] All `get_by_capability()` / `all_with_capability()` calls have corresponding `consumes` or `optional_dependencies` in PluginMeta
- [ ] No tool definitions exist outside the plugin that owns them
- [ ] No `os.environ` reads for secrets (pending [#50](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/50))
- [ ] New plugins don't require edits to existing plugins
- [ ] `ToolProvider` interface used for any LLM-facing tools
- [ ] Plugin graph accurately reflects all edges (`cobot plugins inspect`)
- [ ] `priority` value fits within the correct [band](#priority-bands)
- [ ] Extension points follow the `<plugin_id>.<hook_name>` naming convention

---

## Related Issues

- [#50 — Secret management](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/50) — Principle 5
- [#54 — Plugin introspection](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/54) — Graph must reflect reality
- [#57 — Hidden coupling audit](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/57) — Principle 2
- [#58 — Tool injection refactor](https://forgejo.tail593e12.ts.net/ultanio/cobot/issues/58) — Principle 1

---

*See also: [Architecture](./architecture.md) · [Conventions](./dev/conventions.md) · [Contributing](../CONTRIBUTING.md)*
