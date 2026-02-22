"""Loop plugin - the main agent message loop.

Extracts the poll → context → LLM → tools → send cycle from agent.py
into a plugin. The agent becomes a simple loop runner.

Multiple loop plugins can run concurrently (e.g., agent loop, heartbeat,
DVM listener, cron scheduler).

Priority: 50 (after all service plugins are ready)
Capability: loop
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta
from ..interfaces import LLMProvider, LLMError, ToolProvider


class AggregatedToolProvider(ToolProvider):
    """Aggregates tools from multiple ToolProvider plugins."""

    def __init__(self, providers: list):
        self._providers = providers
        self._tool_map: dict[str, ToolProvider] = {}  # tool_name -> provider
        self._build_tool_map()

    def _build_tool_map(self):
        """Build mapping of tool names to providers."""
        for provider in self._providers:
            try:
                for tool_def in provider.get_definitions():
                    name = tool_def.get("function", {}).get("name")
                    if name and name not in self._tool_map:
                        self._tool_map[name] = provider
            except Exception as e:
                # Note: Can't use self.log_* here as this is a helper class
                print(f"[Loop] Error building tool map: {e}", file=sys.stderr)

    def get_definitions(self) -> list[dict]:
        """Get all tool definitions from all providers."""
        all_tools = []
        seen_names = set()
        for provider in self._providers:
            try:
                for tool_def in provider.get_definitions():
                    name = tool_def.get("function", {}).get("name")
                    if name and name not in seen_names:
                        all_tools.append(tool_def)
                        seen_names.add(name)
            except Exception as e:
                # Note: Can't use self.log_* here as this is a helper class
                print(f"[Loop] Error getting definitions: {e}", file=sys.stderr)
        return all_tools

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute tool via the appropriate provider."""
        provider = self._tool_map.get(tool_name)
        if provider:
            return provider.execute(tool_name, args)
        return f"Error: Unknown tool '{tool_name}'"

    @property
    def restart_requested(self) -> bool:
        """Check if any provider requested restart."""
        for provider in self._providers:
            if hasattr(provider, "restart_requested") and provider.restart_requested:
                return True
        return False


class LoopPlugin(Plugin):
    """Main agent message loop.

    Defines extension points that other plugins implement to participate
    in the message processing pipeline:

    - loop.on_message: Called when a message is received (chain)
    - loop.transform_system_prompt: Modify the system prompt (chain)
    - loop.transform_history: Modify conversation history (chain)
    - loop.before_llm: Called before LLM inference (chain, can abort)
    - loop.after_llm: Called after LLM inference (chain)
    - loop.before_tool: Called before tool execution (chain, can abort)
    - loop.after_tool: Called after tool execution (chain)
    - loop.transform_response: Modify the response text (chain)
    - loop.before_send: Called before sending (chain, can abort)
    - loop.after_send: Called after sending (chain)
    - loop.on_error: Called on error (chain)
    """

    meta = PluginMeta(
        id="loop",
        version="1.0.0",
        capabilities=["loop"],
        dependencies=["config", "communication"],
        extension_points=[
            "session.poll_messages",  # Inject messages into the loop (cron uses this)
            "loop.on_message",
            "loop.transform_system_prompt",
            "loop.transform_history",
            "loop.before_llm",
            "loop.after_llm",
            "loop.before_tool",
            "loop.after_tool",
            "loop.transform_response",
            "loop.before_send",
            "loop.after_send",
            "loop.on_error",
        ],
        priority=50,
    )

    def __init__(self):
        self._config = None
        self._soul: str = "You are Cobot, a helpful AI assistant."
        self._interval: int = 30
        self._processed_events: set[str] = set()
        self._max_tool_rounds: int = 10

    def configure(self, config: dict) -> None:
        self._raw_config = config

    async def start(self) -> None:
        """Load configuration and soul."""
        config_plugin = self._registry.get("config") if self._registry else None
        if config_plugin:
            self._config = config_plugin.get_config()
            if self._config:
                self._interval = self._config.polling_interval
                soul_path = Path(self._config.soul_path)
                if soul_path.exists():
                    self._soul = soul_path.read_text()

        self.log_info(f"Ready (interval={self._interval}s)")

    async def stop(self) -> None:
        pass

    def _get_llm(self) -> Optional[LLMProvider]:
        if self._registry:
            return self._registry.get_by_capability("llm")
        return None

    def _get_comm(self):
        if self._registry:
            return self._registry.get("communication")
        return None

    def _get_tools(self) -> Optional["AggregatedToolProvider"]:
        """Get aggregated tool provider from all ToolProvider plugins."""
        if self._registry:
            providers = self._registry.all_with_capability("tools")
            if providers:
                return AggregatedToolProvider(providers)
        return None

    async def run(self) -> None:
        """Main loop: poll → handle → sleep."""
        comm = self._get_comm()
        if not comm:
            self.log_error("No communication plugin, exiting")
            return

        try:
            while True:
                try:
                    # Poll communication channels
                    messages = list(comm.poll() or [])

                    # Poll extension point for injected messages (cron, etc.)
                    injected = await self.call_extension("session.poll_messages")
                    for msg_list in injected:
                        if isinstance(msg_list, list):
                            messages.extend(msg_list)

                    if messages:
                        await asyncio.gather(
                            *[self._handle_message(msg) for msg in messages],
                            return_exceptions=True,
                        )
                except Exception as e:
                    await self.call_extension_chain(
                        "loop.on_error", {"error": e, "hook": "poll"}
                    )
                await asyncio.sleep(self._interval)
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, msg) -> None:
        """Handle a single incoming message."""
        # Deduplicate
        msg_key = f"{msg.channel_type}:{msg.channel_id}:{msg.id}"
        if msg_key in self._processed_events:
            return
        self._processed_events.add(msg_key)
        if len(self._processed_events) > 1000:
            self._processed_events = set(list(self._processed_events)[500:])

        # Extension: on_message
        ctx = await self.call_extension_chain(
            "loop.on_message",
            {
                "message": msg.content,
                "sender": msg.sender_name,
                "sender_id": msg.sender_id,
                "channel_type": msg.channel_type,
                "channel_id": msg.channel_id,
                "event_id": msg.id,
            },
        )
        if ctx.get("abort"):
            return

        message = ctx.get("message", msg.content)
        response_text = await self._respond(
            message,
            sender=msg.sender_name,
            channel_type=msg.channel_type,
            channel_id=msg.channel_id,
        )

        # Extension: before_send
        ctx = await self.call_extension_chain(
            "loop.before_send",
            {"text": response_text, "recipient": msg.sender_name},
        )
        if ctx.get("abort"):
            return
        response_text = ctx.get("text", response_text)

        # Send
        comm = self._get_comm()
        if comm:
            from ..communication import OutgoingMessage

            success = comm.send(
                OutgoingMessage(
                    channel_type=msg.channel_type,
                    channel_id=msg.channel_id,
                    content=response_text,
                    reply_to=msg.id,
                )
            )
            if success:
                await self.call_extension_chain(
                    "loop.after_send",
                    {
                        "text": response_text,
                        "recipient": msg.sender_name,
                        "channel_type": msg.channel_type,
                        "channel_id": msg.channel_id,
                    },
                )
            else:
                await self.call_extension_chain(
                    "loop.on_error", {"error": "Send failed", "hook": "send"}
                )

        # Check restart
        tools = self._get_tools()
        if tools and tools.restart_requested:
            await self._do_restart()

    async def _respond(
        self,
        message: str,
        sender: str = "unknown",
        channel_type: str = "",
        channel_id: str = "",
    ) -> str:
        """Generate a response using LLM + tools."""
        llm = self._get_llm()
        tools = self._get_tools()

        if not llm:
            return "Error: No LLM configured"

        messages = [
            {"role": "system", "content": self._soul},
            {"role": "user", "content": message},
        ]

        # Extension: transform_system_prompt
        ctx = await self.call_extension_chain(
            "loop.transform_system_prompt",
            {"prompt": self._soul, "peer": sender, "messages": messages},
        )
        messages[0]["content"] = ctx.get("prompt", self._soul)

        # Extension: transform_history
        ctx = await self.call_extension_chain(
            "loop.transform_history",
            {"messages": messages, "peer": sender},
        )
        messages = ctx.get("messages", messages)

        tool_defs = tools.get_definitions() if tools else []

        try:
            for _ in range(self._max_tool_rounds):
                # Extension: before_llm
                ctx = await self.call_extension_chain(
                    "loop.before_llm",
                    {
                        "messages": messages,
                        "model": self._config.provider if self._config else "unknown",
                        "tools": tool_defs,
                        "channel_type": channel_type,
                        "channel_id": channel_id,
                    },
                )
                if ctx.get("abort"):
                    return ctx.get("abort_message", "Request aborted.")

                response = llm.chat(messages, tools=tool_defs if tool_defs else None)

                # Extension: after_llm
                await self.call_extension_chain(
                    "loop.after_llm",
                    {
                        "response": response.content,
                        "model": response.model,
                        "tokens_in": response.tokens_in,
                        "tokens_out": response.tokens_out,
                        "has_tool_calls": response.has_tool_calls,
                    },
                )

                if not response.has_tool_calls:
                    break

                # Process tool calls
                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content,
                        "tool_calls": response.tool_calls,
                    }
                )

                for tool_call in response.tool_calls:
                    tool_name = tool_call["function"]["name"]
                    raw_args = tool_call["function"]["arguments"]
                    tool_args = (
                        json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                    tool_id = tool_call["id"]

                    # Extension: before_tool
                    ctx = await self.call_extension_chain(
                        "loop.before_tool",
                        {"tool": tool_name, "args": tool_args},
                    )
                    if ctx.get("abort"):
                        result = ctx.get("abort_message", "Blocked.")
                    elif tools:
                        result = tools.execute(tool_name, tool_args)
                    else:
                        result = "Error: Tools not available"

                    # Extension: after_tool
                    await self.call_extension_chain(
                        "loop.after_tool",
                        {"tool": tool_name, "args": tool_args, "result": result},
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": result,
                        }
                    )

            # Extension: transform_response
            ctx = await self.call_extension_chain(
                "loop.transform_response",
                {"text": response.content or "", "recipient": sender},
            )

            final_text = ctx.get("text", response.content or "")
            if not final_text.strip():
                final_text = "(No response generated)"
            return final_text

        except LLMError as e:
            await self.call_extension_chain(
                "loop.on_error", {"error": e, "hook": "llm_call"}
            )
            return f"Error: {e}"

    async def _do_restart(self):
        """Restart the agent process."""
        import os
        import subprocess

        if self._registry:
            await self._registry.stop_all()

        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "cobot"], check=True, timeout=5
            )
        except Exception:
            os.execv(sys.executable, [sys.executable] + sys.argv)


def create_plugin() -> LoopPlugin:
    return LoopPlugin()
