"""Pure-function plugin dependency resolver.

Resolves which plugins to load and in what order, given:
- Discovered plugin metadata (as lightweight PluginNode objects)
- Load policy (enable/disable)
- Enabled/disabled lists
- LLM provider selection
- Core plugin IDs

All functions are pure — no side effects, no logging, no imports of plugin classes.
"""

from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass, field

from .registry import PluginError


@dataclass
class PluginNode:
    """Lightweight plugin representation for resolution (no instantiation needed)."""

    id: str
    dependencies: list[str] = field(default_factory=list)
    optional_dependencies: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    priority: int = 50


@dataclass
class ResolveResult:
    """Resolution output."""

    load_order: list[str]  # Topologically sorted plugin IDs to load
    load_reasons: dict[str, str]  # plugin_id → "direct" | "transitive" | "core"
    skipped: dict[str, str]  # plugin_id → reason not loaded
    warnings: list[str]  # Non-fatal diagnostics


def resolve(
    discovered: dict[str, PluginNode],
    policy: str = "enable",
    enabled: list[str] | None = None,
    disabled: list[str] | None = None,
    provider: str = "ppq",
    core_ids: list[str] | None = None,
) -> ResolveResult:
    """Resolve plugin dependency tree and produce topological load order.

    Args:
        discovered: All discovered plugins as PluginNode objects.
        policy: "enable" (load all, use disabled to exclude) or
                "disable" (load nothing, use enabled to include).
        enabled: Plugins to explicitly enable (used with policy=disable).
        disabled: Plugins to explicitly disable (used with policy=enable).
        provider: Selected LLM provider ID.
        core_ids: Plugin IDs that always load (e.g., ["config", "logger"]).

    Returns:
        ResolveResult with load_order, load_reasons, skipped, warnings.

    Raises:
        PluginError: On invalid policy, cycles, conflicts, or missing deps.
    """
    enabled = enabled or []
    disabled = disabled or []
    core_ids = core_ids or []
    warnings: list[str] = []

    # Validate policy
    if policy not in ("enable", "disable"):
        raise PluginError(
            f"Invalid plugins.policy: '{policy}'. Must be 'enable' or 'disable'."
        )

    # --- Phase 1: Determine enabled set ---
    reasons: dict[str, str] = {}
    disabled_set = set(disabled)

    if policy == "enable":
        enabled_set = set(discovered.keys())
        # Remove explicitly disabled
        enabled_set -= disabled_set
        # Remove non-selected LLM providers
        for pid, node in discovered.items():
            if "llm" in node.capabilities and pid != provider:
                enabled_set.discard(pid)
        reasons = {pid: "direct" for pid in enabled_set}
    else:  # policy == "disable"
        enabled_set = set(enabled)
        # Validate enabled plugins exist
        for pid in enabled_set:
            if pid not in discovered:
                raise PluginError(
                    f"Plugin '{pid}' in plugins.enabled not found. "
                    f"Available: {sorted(discovered.keys())}"
                )
        reasons = {pid: "direct" for pid in enabled_set}

    # Always add core plugins
    for cid in core_ids:
        if cid in discovered:
            enabled_set.add(cid)
            reasons[cid] = "core"

    # Always add selected provider if it exists
    if provider in discovered:
        enabled_set.add(provider)
        reasons[provider] = "core"
    elif policy == "disable":
        # Only error if explicitly using disable mode (enable mode may just not have it)
        pass

    # --- Phase 2: Resolve transitive dependencies ---
    resolved = set(enabled_set)
    queue = deque(enabled_set)

    while queue:
        pid = queue.popleft()
        node = discovered.get(pid)
        if node is None:
            raise PluginError(
                f"Plugin '{pid}' required but not found in discovered plugins."
            )
        for dep in node.dependencies:
            if dep not in discovered:
                raise PluginError(
                    f"Plugin '{pid}' requires '{dep}', which is not installed."
                )
            if dep in disabled_set:
                raise PluginError(
                    f"Plugin '{pid}' requires '{dep}', which is in plugins.disabled.\n"
                    f"  Fix: Remove '{dep}' from plugins.disabled, or remove '{pid}' from plugins.enabled."
                )
            if dep not in resolved:
                resolved.add(dep)
                reasons[dep] = "transitive"
                queue.append(dep)

    # --- Phase 3: Topological sort (Kahn's algorithm with priority tiebreaker) ---
    in_degree: dict[str, int] = {pid: 0 for pid in resolved}
    adj: dict[str, list[str]] = {pid: [] for pid in resolved}

    for pid in resolved:
        for dep in discovered[pid].dependencies:
            if dep in resolved:
                adj[dep].append(pid)
                in_degree[pid] += 1

    # Min-heap keyed by (priority, plugin_id) for stable ordering
    heap: list[tuple[int, str]] = [
        (discovered[pid].priority, pid) for pid in resolved if in_degree[pid] == 0
    ]
    heapq.heapify(heap)

    order: list[str] = []
    while heap:
        _pri, pid = heapq.heappop(heap)
        order.append(pid)
        for dependent in adj[pid]:
            in_degree[dependent] -= 1
            if in_degree[dependent] == 0:
                heapq.heappush(heap, (discovered[dependent].priority, dependent))

    if len(order) != len(resolved):
        # Cycle exists — find it for error reporting
        remaining = resolved - set(order)
        cycle_path = _find_cycle(discovered, remaining)
        raise PluginError(f"Circular dependency detected: {' → '.join(cycle_path)}")

    # --- Build skipped dict ---
    skipped: dict[str, str] = {}
    for pid in discovered:
        if pid not in resolved:
            if pid in disabled_set:
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


def _find_cycle(discovered: dict[str, PluginNode], remaining: set[str]) -> list[str]:
    """Find a cycle in the remaining (unresolved) nodes using DFS 3-color marking.

    Returns the cycle as a list of plugin IDs forming the loop.
    """
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {pid: WHITE for pid in remaining}
    path: list[str] = []

    def dfs(pid: str) -> list[str] | None:
        color[pid] = GRAY
        path.append(pid)
        node = discovered.get(pid)
        if node:
            for dep in node.dependencies:
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

    return list(remaining)  # fallback — shouldn't happen
