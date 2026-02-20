"""Tests for plugin system (registry, base, interfaces)."""

import asyncio
import pytest

from cobot.plugins import (
    Plugin,
    PluginMeta,
    HOOK_METHODS,
    PluginRegistry,
    PluginError,
    get_registry,
    reset_registry,
    LLMProvider,
    LLMResponse,
    LLMError,
    Message,
    CommunicationError,
    WalletError,
    run,
)


# --- Test Plugin Classes ---


class DummyPlugin(Plugin):
    """A simple test plugin."""

    meta = PluginMeta(
        id="dummy",
        version="1.0.0",
        capabilities=["test"],
        dependencies=[],
        priority=50,
    )

    def __init__(self):
        self.configured = False
        self.started = False
        self.stopped = False
        self.config_received = None

    def configure(self, config: dict) -> None:
        self.configured = True
        self.config_received = config

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class HighPriorityPlugin(Plugin):
    """Plugin with high priority (loads first)."""

    meta = PluginMeta(
        id="high_priority",
        version="1.0.0",
        capabilities=["test"],
        dependencies=[],
        priority=1,
    )

    def configure(self, config: dict) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class LowPriorityPlugin(Plugin):
    """Plugin with low priority (loads last)."""

    meta = PluginMeta(
        id="low_priority",
        version="1.0.0",
        capabilities=["test"],
        dependencies=["high_priority"],
        priority=100,
    )

    def configure(self, config: dict) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class DummyLLMPlugin(Plugin, LLMProvider):
    """Test LLM plugin."""

    meta = PluginMeta(
        id="dummy_llm",
        version="1.0.0",
        capabilities=["llm"],
        dependencies=[],
        priority=20,
    )

    def configure(self, config: dict) -> None:
        pass

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def chat(self, messages, tools=None, model=None, max_tokens=2048):
        return LLMResponse(content="Hello from dummy LLM!", model="dummy")


# --- Tests ---


class TestPluginMeta:
    """Test PluginMeta dataclass."""

    def test_create_meta(self):
        meta = PluginMeta(
            id="test",
            version="1.0.0",
            capabilities=["llm"],
            dependencies=["config"],
            priority=10,
        )
        assert meta.id == "test"
        assert meta.version == "1.0.0"
        assert "llm" in meta.capabilities
        assert "config" in meta.dependencies
        assert meta.priority == 10

    def test_default_values(self):
        meta = PluginMeta(id="test", version="1.0.0")
        assert meta.capabilities == []
        assert meta.dependencies == []
        assert meta.priority == 50


class TestPluginRegistry:
    """Test PluginRegistry class."""

    @pytest.fixture(autouse=True)
    def reset(self):
        """Reset global registry before each test."""
        reset_registry()
        yield
        reset_registry()

    def test_register_plugin(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)

        assert registry.get("dummy") is not None

    def test_get_nonexistent_plugin(self):
        registry = PluginRegistry()
        assert registry.get("nonexistent") is None

    def test_get_by_capability(self):
        registry = PluginRegistry()
        registry.register(DummyLLMPlugin)

        llm = registry.get_by_capability("llm")
        assert llm is not None
        assert isinstance(llm, LLMProvider)

    def test_get_by_capability_no_match(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)

        llm = registry.get_by_capability("llm")
        assert llm is None

    def test_all_with_capability(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)
        registry.register(HighPriorityPlugin)

        test_plugins = registry.all_with_capability("test")
        assert len(test_plugins) == 2

    def test_priority_ordering(self):
        registry = PluginRegistry()
        registry.register(LowPriorityPlugin)
        registry.register(HighPriorityPlugin)
        registry.register(DummyPlugin)

        # Configure to trigger load order resolution
        registry.configure_all({})

        # Check load order is by priority
        ids = registry._load_order

        # Should be sorted by priority: high(1) < dummy(50) < low(100)
        assert ids.index("high_priority") < ids.index("dummy")
        assert ids.index("dummy") < ids.index("low_priority")

    def test_configure_all(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)

        config = {"dummy": {"key": "value"}}
        registry.configure_all(config)

        plugin = registry.get("dummy")
        assert plugin.configured is True
        # Registry now passes full config, plugin extracts its own section
        assert plugin.config_received == config

    def test_start_all(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)
        registry.configure_all({})

        asyncio.run(registry.start_all())

        plugin = registry.get("dummy")
        assert plugin.started is True

    def test_stop_all(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)
        registry.configure_all({})
        asyncio.run(registry.start_all())

        asyncio.run(registry.stop_all())

        plugin = registry.get("dummy")
        assert plugin.stopped is True

    def test_duplicate_registration_raises(self):
        registry = PluginRegistry()
        registry.register(DummyPlugin)

        with pytest.raises(PluginError):
            registry.register(DummyPlugin)


class TestGlobalRegistry:
    """Test global registry functions."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_registry()
        yield
        reset_registry()

    def test_get_registry_returns_singleton(self):
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_reset_registry(self):
        reg1 = get_registry()
        reg1.register(DummyPlugin)

        reset_registry()

        reg2 = get_registry()
        assert reg2.get("dummy") is None


class TestHookMethods:
    """Test hook method constants."""

    def test_hook_methods_defined(self):
        # Core hooks (now namespaced under loop.*)
        assert "loop.on_message" in HOOK_METHODS
        assert "loop.before_llm" in HOOK_METHODS
        assert "loop.after_llm" in HOOK_METHODS
        assert "loop.before_tool" in HOOK_METHODS
        assert "loop.after_tool" in HOOK_METHODS
        assert "loop.on_error" in HOOK_METHODS

        # Transform hooks
        assert "loop.transform_system_prompt" in HOOK_METHODS
        assert "loop.transform_history" in HOOK_METHODS
        assert "loop.transform_response" in HOOK_METHODS


class TestInterfaces:
    """Test capability interface classes."""

    def test_llm_response(self):
        response = LLMResponse(content="hello", model="test")
        assert response.content == "hello"
        assert response.has_tool_calls is False

    def test_llm_response_with_tools(self):
        response = LLMResponse(
            content="",
            tool_calls=[{"id": "1", "function": {"name": "test"}}],
            model="test",
        )
        assert response.has_tool_calls is True

    def test_message(self):
        msg = Message(id="1", sender="alice", content="hello", timestamp=12345)
        assert msg.id == "1"
        assert msg.sender == "alice"
        assert msg.content == "hello"

    def test_llm_error(self):
        error = LLMError("API failed")
        assert str(error) == "API failed"

    def test_communication_error(self):
        error = CommunicationError("Connection lost")
        assert str(error) == "Connection lost"

    def test_wallet_error(self):
        error = WalletError("Insufficient funds")
        assert str(error) == "Insufficient funds"


class TestRunHook:
    """Test the run() hook function."""

    @pytest.fixture(autouse=True)
    def reset(self):
        reset_registry()
        yield
        reset_registry()

    def test_run_returns_context(self):
        result = asyncio.run(run("test_hook", {"value": 42}))
        assert result["value"] == 42

    def test_run_nonexistent_hook(self):
        result = asyncio.run(run("nonexistent", {"value": 1}))
        assert result["value"] == 1  # Returns context unchanged
