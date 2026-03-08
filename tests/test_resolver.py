"""Tests for cobot.plugins.resolver — pure-function dependency resolution."""

import pytest

from cobot.plugins.resolver import PluginNode, ResolveResult, resolve
from cobot.plugins.registry import PluginError


def _node(id, deps=None, caps=None, pri=50, opt_deps=None):
    """Helper to create PluginNode with defaults."""
    return PluginNode(
        id=id,
        dependencies=deps or [],
        optional_dependencies=opt_deps or [],
        capabilities=caps or [],
        priority=pri,
    )


# --- Fixtures: common plugin sets ---

@pytest.fixture
def core_nodes():
    """Minimal core plugins."""
    return {
        "config": _node("config", pri=1, caps=["config"]),
        "logger": _node("logger", pri=5, caps=["logging"]),
    }


@pytest.fixture
def full_nodes():
    """Realistic set mirroring actual cobot plugins."""
    return {
        "config": _node("config", pri=1, caps=["config"]),
        "logger": _node("logger", pri=5, caps=["logging"]),
        "workspace": _node("workspace", deps=["config"], pri=5, caps=["workspace"]),
        "communication": _node("communication", pri=50),
        "session": _node("session", deps=["communication"], pri=50),
        "telegram": _node("telegram", deps=["session"], pri=30, caps=["communication"]),
        "ppq": _node("ppq", deps=["config"], pri=20, caps=["llm"]),
        "ollama": _node("ollama", deps=["config"], pri=20, caps=["llm"]),
        "loop": _node("loop", deps=["config", "communication"], pri=50, caps=["loop"]),
        "cron": _node("cron", deps=["config"], pri=40, caps=["cron", "tools"]),
        "heartbeat": _node("heartbeat", deps=["cron"], pri=45),
        "memory": _node("memory", deps=["workspace"], pri=50),
        "memory-files": _node("memory-files", deps=["workspace", "memory"], pri=14),
        "nostr": _node("nostr", deps=["config"], pri=25, caps=["communication"]),
        "security": _node("security", deps=["config"], pri=10, caps=["security"]),
        "tools": _node("tools", deps=["config"], pri=30, caps=["tools"]),
        "web": _node("web", deps=["config"], pri=30),
    }


CORE_IDS = ["config", "logger"]


# ============================================================
# Epic 1 / Story 1.1: Data Structures
# ============================================================

class TestDataStructures:
    def test_plugin_node_defaults(self):
        node = PluginNode(id="test")
        assert node.dependencies == []
        assert node.optional_dependencies == []
        assert node.capabilities == []
        assert node.consumes == []
        assert node.priority == 50

    def test_resolve_result_fields(self):
        r = ResolveResult(
            load_order=["a"], load_reasons={"a": "direct"},
            skipped={}, warnings=[]
        )
        assert r.load_order == ["a"]


# ============================================================
# Epic 1 / Story 1.2: Transitive Dependency Resolution
# ============================================================

class TestTransitiveDeps:
    def test_single_no_deps(self, core_nodes):
        nodes = {**core_nodes, "web": _node("web", deps=["config"], pri=30)}
        result = resolve(nodes, policy="disable", enabled=["web"],
                         provider="ppq", core_ids=CORE_IDS)
        assert "web" in result.load_order
        assert "config" in result.load_order
        assert "logger" in result.load_order

    def test_transitive_chain(self, core_nodes):
        nodes = {
            **core_nodes,
            "communication": _node("communication", pri=50),
            "session": _node("session", deps=["communication"], pri=50),
            "telegram": _node("telegram", deps=["session"], pri=30),
        }
        result = resolve(nodes, policy="disable", enabled=["telegram"],
                         provider="ppq", core_ids=CORE_IDS)
        order = result.load_order
        assert "telegram" in order
        assert "session" in order
        assert "communication" in order
        # Verify ordering: deps before dependents
        assert order.index("communication") < order.index("session")
        assert order.index("session") < order.index("telegram")

    def test_diamond_dependency(self, core_nodes):
        nodes = {
            **core_nodes,
            "D": _node("D", pri=10),
            "B": _node("B", deps=["D"], pri=20),
            "C": _node("C", deps=["D"], pri=20),
            "A": _node("A", deps=["B", "C"], pri=30),
        }
        result = resolve(nodes, policy="disable", enabled=["A"],
                         provider="ppq", core_ids=CORE_IDS)
        assert result.load_order.count("D") == 1
        assert result.load_order.index("D") < result.load_order.index("B")
        assert result.load_order.index("D") < result.load_order.index("C")

    def test_missing_dependency_raises(self, core_nodes):
        nodes = {**core_nodes, "X": _node("X", deps=["Y"])}
        with pytest.raises(PluginError, match="requires 'Y'.*not installed"):
            resolve(nodes, policy="disable", enabled=["X"],
                    provider="ppq", core_ids=CORE_IDS)

    def test_disabled_dependency_raises(self, core_nodes):
        nodes = {
            **core_nodes,
            "cron": _node("cron", deps=["config"], pri=40),
            "heartbeat": _node("heartbeat", deps=["cron"], pri=45),
        }
        with pytest.raises(PluginError, match="requires 'cron'.*plugins.disabled"):
            resolve(nodes, policy="enable", enabled=[],
                    disabled=["cron"], provider="ppq", core_ids=CORE_IDS)


# ============================================================
# Epic 1 / Story 1.3: Cycle Detection
# ============================================================

class TestCycleDetection:
    def test_simple_cycle(self, core_nodes):
        nodes = {
            **core_nodes,
            "A": _node("A", deps=["B"]),
            "B": _node("B", deps=["C"]),
            "C": _node("C", deps=["A"]),
        }
        with pytest.raises(PluginError, match="Circular dependency detected"):
            resolve(nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)

    def test_self_reference(self, core_nodes):
        nodes = {**core_nodes, "A": _node("A", deps=["A"])}
        with pytest.raises(PluginError, match="Circular dependency detected"):
            resolve(nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)

    def test_no_cycle_in_real_plugins(self, full_nodes):
        """All real cobot plugins should resolve without cycles."""
        result = resolve(full_nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        assert len(result.load_order) > 0


# ============================================================
# Epic 1 / Story 1.4: Topological Sort with Priority Tiebreaker
# ============================================================

class TestTopologicalSort:
    def test_dependency_order(self, core_nodes):
        nodes = {
            **core_nodes,
            "workspace": _node("workspace", deps=["config"], pri=5),
            "memory": _node("memory", deps=["workspace"], pri=12),
        }
        result = resolve(nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        order = result.load_order
        assert order.index("config") < order.index("workspace")
        assert order.index("workspace") < order.index("memory")

    def test_priority_tiebreaker(self, core_nodes):
        """Unrelated plugins sorted by priority."""
        nodes = {
            **core_nodes,
            "cli": _node("cli", pri=5),
            "security": _node("security", deps=["config"], pri=10),
            "web": _node("web", deps=["config"], pri=30),
        }
        result = resolve(nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        order = result.load_order
        # cli (pri=5) before security (pri=10) before web (pri=30)
        assert order.index("cli") < order.index("security")
        assert order.index("security") < order.index("web")

    def test_full_set_deps_before_dependents(self, full_nodes):
        """Every plugin appears after all its declared dependencies."""
        result = resolve(full_nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        order = result.load_order
        for pid in order:
            node = full_nodes[pid]
            for dep in node.dependencies:
                if dep in order:
                    assert order.index(dep) < order.index(pid), \
                        f"{dep} should come before {pid}"


# ============================================================
# Epic 1 / Story 1.5: Top-Level resolve()
# ============================================================

class TestResolveFunction:
    def test_policy_enable_default(self, full_nodes):
        """Policy enable with no disabled = all plugins minus non-selected providers."""
        result = resolve(full_nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        assert "ollama" not in result.load_order
        assert "ollama" in result.skipped
        assert result.skipped["ollama"] == "provider-skip"
        # All non-ollama plugins should be loaded
        for pid in full_nodes:
            if pid != "ollama":
                assert pid in result.load_order

    def test_policy_disable_minimal(self, full_nodes):
        """Policy disable with enabled=[telegram] loads telegram + deps + core."""
        result = resolve(full_nodes, policy="disable", enabled=["telegram"],
                         provider="ppq", core_ids=CORE_IDS)
        expected = {"config", "logger", "ppq", "communication", "session", "telegram"}
        assert set(result.load_order) == expected
        assert result.load_reasons["config"] == "core"
        assert result.load_reasons["logger"] == "core"
        assert result.load_reasons["ppq"] == "core"
        assert result.load_reasons["telegram"] == "direct"
        assert result.load_reasons["communication"] == "transitive"
        assert result.load_reasons["session"] == "transitive"

    def test_policy_disable_skipped(self, full_nodes):
        """Policy disable: unreachable plugins are skipped."""
        result = resolve(full_nodes, policy="disable", enabled=["telegram"],
                         provider="ppq", core_ids=CORE_IDS)
        assert "nostr" in result.skipped
        assert result.skipped["nostr"] == "not-reachable"
        assert "heartbeat" in result.skipped

    def test_backward_compat_enabled_list(self, full_nodes):
        """No policy key + enabled list: policy defaults to enable, all load."""
        result = resolve(full_nodes, policy="enable", enabled=["telegram", "loop"],
                         provider="ppq", core_ids=CORE_IDS)
        # With policy=enable, all plugins load regardless of enabled list
        for pid in full_nodes:
            if pid != "ollama":
                assert pid in result.load_order

    def test_empty_discovered(self):
        """Empty discovered set returns empty result."""
        result = resolve({}, policy="enable", provider="ppq", core_ids=CORE_IDS)
        assert result.load_order == []
        assert result.skipped == {}


# ============================================================
# Epic 2 / Story 2.1-2.2: Policy Validation
# ============================================================

class TestPolicyValidation:
    def test_invalid_policy(self, core_nodes):
        with pytest.raises(PluginError, match="Invalid plugins.policy"):
            resolve(core_nodes, policy="bogus", core_ids=CORE_IDS)

    def test_enabled_not_found(self, core_nodes):
        with pytest.raises(PluginError, match="not found"):
            resolve(core_nodes, policy="disable", enabled=["nonexistent"],
                    provider="ppq", core_ids=CORE_IDS)


# ============================================================
# Epic 2 / Story 2.5: Provider Selection
# ============================================================

class TestProviderSelection:
    def test_provider_loads_correct(self, full_nodes):
        result = resolve(full_nodes, policy="enable", provider="ollama", core_ids=CORE_IDS)
        assert "ollama" in result.load_order
        assert "ppq" not in result.load_order
        assert result.skipped["ppq"] == "provider-skip"

    def test_provider_in_disable_mode(self, full_nodes):
        result = resolve(full_nodes, policy="disable", enabled=["telegram"],
                         provider="ppq", core_ids=CORE_IDS)
        assert "ppq" in result.load_order
        assert result.load_reasons["ppq"] == "core"


# ============================================================
# Epic 3 / Story 3.3: Load Order Used for Lifecycle
# ============================================================

class TestLifecycleOrder:
    def test_start_stop_order(self, full_nodes):
        """Verify reverse order for stop is the reverse of load_order."""
        result = resolve(full_nodes, policy="disable", enabled=["telegram"],
                         provider="ppq", core_ids=CORE_IDS)
        stop_order = list(reversed(result.load_order))
        # telegram should stop first, config last
        assert stop_order[0] == "telegram"
        assert stop_order[-1] in ("config", "logger")


# ============================================================
# Epic 5 / Story 5.4: Full 29-Plugin Audit
# ============================================================

class TestFullPluginSet:
    """Test with all 29 actual cobot plugin metadata."""

    @pytest.fixture
    def all_29_nodes(self):
        return {
            "config": _node("config", pri=1, caps=["config"]),
            "logger": _node("logger", pri=5, caps=["logging"]),
            "cli": _node("cli", pri=5),
            "workspace": _node("workspace", deps=["config"], pri=5, caps=["workspace"]),
            "communication": _node("communication", pri=50),
            "security": _node("security", deps=["config"], pri=10, caps=["security"]),
            "memory": _node("memory", deps=["workspace"], pri=50),
            "memory-files": _node("memory-files", deps=["workspace", "memory"], pri=14),
            "soul": _node("soul", deps=["workspace"], pri=15),
            "persistence": _node("persistence", deps=["config", "workspace"], pri=15, caps=["persistence"]),
            "compaction": _node("compaction", deps=["config", "persistence"], pri=16, caps=["compaction"]),
            "trust": _node("trust", deps=["config"], pri=16),
            "context": _node("context", deps=["config"], pri=18),
            "skills": _node("skills", deps=["config"], pri=19, caps=["tools"], opt_deps=["workspace"]),
            "ppq": _node("ppq", deps=["config"], pri=20, caps=["llm"]),
            "ollama": _node("ollama", deps=["config"], pri=20, caps=["llm"]),
            "knowledge": _node("knowledge", deps=["config"], pri=22, caps=["knowledge", "tools"]),
            "filedrop": _node("filedrop", deps=["config"], pri=24, caps=["communication"]),
            "nostr": _node("nostr", deps=["config"], pri=25, caps=["communication"]),
            "wallet": _node("wallet", deps=["config"], pri=25, caps=["wallet", "tools"]),
            "pairing": _node("pairing", deps=["config"], pri=5, caps=["pairing"], opt_deps=["communication"]),
            "tools": _node("tools", deps=["config"], pri=30, caps=["tools"]),
            "web": _node("web", deps=["config"], pri=30),
            "telegram": _node("telegram", deps=["session"], pri=30, caps=["communication"]),
            "subagent": _node("subagent", deps=["config"], pri=32, caps=["subagent", "tools"]),
            "session": _node("session", deps=["communication"], pri=50),
            "cron": _node("cron", deps=["config"], pri=40, caps=["cron", "tools"], opt_deps=["subagent", "communication", "filedrop"]),
            "heartbeat": _node("heartbeat", deps=["cron"], pri=45),
            "loop": _node("loop", deps=["config", "communication"], pri=50, caps=["loop"]),
        }

    def test_enable_all_resolves(self, all_29_nodes):
        result = resolve(all_29_nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        assert len(result.load_order) == 28  # 29 minus ollama
        assert "ollama" in result.skipped

    def test_disable_mode_resolves(self, all_29_nodes):
        result = resolve(all_29_nodes, policy="disable",
                         enabled=["telegram", "loop"], provider="ppq", core_ids=CORE_IDS)
        expected = {"config", "logger", "ppq", "communication", "session", "telegram", "loop"}
        assert set(result.load_order) == expected

    def test_all_deps_before_dependents(self, all_29_nodes):
        result = resolve(all_29_nodes, policy="enable", provider="ppq", core_ids=CORE_IDS)
        order = result.load_order
        for pid in order:
            for dep in all_29_nodes[pid].dependencies:
                if dep in order:
                    assert order.index(dep) < order.index(pid), \
                        f"{dep} must come before {pid}"

    def test_disable_heartbeat_pulls_cron(self, all_29_nodes):
        """In disable mode, enabling heartbeat transitively pulls in cron."""
        result = resolve(all_29_nodes, policy="disable",
                         enabled=["heartbeat"], disabled=[],
                         provider="ppq", core_ids=CORE_IDS)
        assert "cron" in result.load_order
        assert result.load_reasons["cron"] == "transitive"
        assert result.load_reasons["heartbeat"] == "direct"

    def test_enable_with_disabled_conflict(self, all_29_nodes):
        """policy=enable with disabled=[cron] should fail because heartbeat needs cron."""
        with pytest.raises(PluginError, match="requires 'cron'.*plugins.disabled"):
            resolve(all_29_nodes, policy="enable", disabled=["cron"],
                    provider="ppq", core_ids=CORE_IDS)
