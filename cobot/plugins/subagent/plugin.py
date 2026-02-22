"""Subagent plugin - spawn isolated sessions for delegated work.

Provides isolated execution for:
- Long-running tasks
- Parallel work
- Delegated specialist tasks

Subagents run without conversation history or memory context.
They receive only the explicit task and context provided.

Priority: 32 (after main tools at 30)
Capabilities: subagent, tools (partial - provides spawn_subagent tool)
"""

import asyncio
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import click
from typing import Optional

from ..base import Plugin, PluginMeta
from ..interfaces import ToolProvider


# --- Subagent Interface ---


@dataclass
class SubagentResult:
    """Result from a subagent execution."""

    success: bool
    output: str
    task: str
    elapsed_seconds: float
    error: Optional[str] = None


class SubagentProvider(ABC):
    """Interface for subagent plugins.

    Provides isolated session execution for delegated work.
    """

    @abstractmethod
    async def spawn(
        self,
        task: str,
        context: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> SubagentResult:
        """Spawn an isolated subagent session.

        Args:
            task: Task description for the subagent
            context: Optional context data to include
            system_prompt: Override system prompt (default: generic)
            timeout_seconds: Kill subagent after this time

        Returns:
            SubagentResult with output and metadata
        """
        pass


# Tool definition for agent use
SUBAGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_subagent",
        "description": (
            "Spawn an isolated subagent for a delegated task. "
            "Use for long-running work, parallel research, or specialist tasks. "
            "The subagent has no access to conversation history or memory."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "Task description for the subagent",
                },
                "context": {
                    "type": "string",
                    "description": "Optional context data (JSON string or plain text)",
                },
                "timeout_minutes": {
                    "type": "integer",
                    "default": 5,
                    "description": "Timeout in minutes (default 5, max 30)",
                },
            },
            "required": ["task"],
        },
    },
}


class SubagentPlugin(Plugin, SubagentProvider, ToolProvider):
    """Subagent plugin for isolated session execution."""

    meta = PluginMeta(
        id="subagent",
        version="1.0.0",
        capabilities=["subagent", "tools"],
        dependencies=["config"],
        consumes=["llm"],
        priority=32,  # After main tools
        extension_points=[
            "subagent.before_spawn",  # Modify task/context before spawn
            "subagent.after_spawn",  # Process result after spawn
        ],
        implements={"cli.commands": "register_commands"},
    )

    def __init__(self):
        self._config: dict = {}
        self._max_concurrent: int = 3
        self._default_timeout: int = 300
        self._max_timeout: int = 1800  # 30 minutes
        self._active_count: int = 0
        self._lock = asyncio.Lock()
        self._restart_requested: bool = False

    def configure(self, config: dict) -> None:
        """Configure subagent settings."""
        subagent_config = config.get("subagent", {})
        self._max_concurrent = subagent_config.get("max_concurrent", 3)
        self._default_timeout = subagent_config.get("default_timeout_seconds", 300)
        self._max_timeout = subagent_config.get("max_timeout_seconds", 1800)
        self._config = subagent_config

    async def start(self) -> None:
        """Initialize plugin."""
        self.log_info(f"Ready (max_concurrent={self._max_concurrent})")

    async def stop(self) -> None:
        """Clean up."""
        pass

    # --- SubagentProvider Interface ---

    async def spawn(
        self,
        task: str,
        context: Optional[dict] = None,
        system_prompt: Optional[str] = None,
        timeout_seconds: int = 300,
    ) -> SubagentResult:
        """Spawn an isolated subagent session."""
        # Check concurrency limit
        async with self._lock:
            if self._active_count >= self._max_concurrent:
                return SubagentResult(
                    success=False,
                    output="",
                    task=task,
                    elapsed_seconds=0,
                    error=f"Concurrency limit reached ({self._max_concurrent})",
                )
            self._active_count += 1

        start_time = time.time()
        try:
            # Call extension point: before_spawn
            ctx = {"task": task, "context": context, "system_prompt": system_prompt}
            results = await self.call_extension("subagent.before_spawn", ctx)
            if results:
                ctx = results[-1]  # Use last result

            # Get LLM provider
            llm = self._registry.get_by_capability("llm") if self._registry else None
            if not llm:
                return SubagentResult(
                    success=False,
                    output="",
                    task=task,
                    elapsed_seconds=time.time() - start_time,
                    error="No LLM provider available",
                )

            # Build isolated prompt
            prompt = self._build_prompt(
                ctx.get("task", task),
                ctx.get("context", context),
            )

            # Build messages
            sys_prompt = ctx.get("system_prompt", system_prompt) or (
                "You are a subagent spawned for a specific task. "
                "Complete your task efficiently and report your findings. "
                "Be concise but thorough. You have no access to conversation "
                "history or memory from the main session."
            )

            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": prompt},
            ]

            # Clamp timeout
            timeout = min(timeout_seconds, self._max_timeout)

            # Execute with timeout
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(llm.chat, messages, tools=None),
                    timeout=timeout,
                )
                output = response.content or ""
                elapsed = time.time() - start_time

                result = SubagentResult(
                    success=True,
                    output=output,
                    task=task,
                    elapsed_seconds=elapsed,
                )

            except asyncio.TimeoutError:
                elapsed = time.time() - start_time
                result = SubagentResult(
                    success=False,
                    output="",
                    task=task,
                    elapsed_seconds=elapsed,
                    error=f"Timeout after {timeout} seconds",
                )

            # Call extension point: after_spawn
            await self.call_extension(
                "subagent.after_spawn",
                {"task": task, "result": result},
            )

            return result

        finally:
            async with self._lock:
                self._active_count -= 1

    def _build_prompt(self, task: str, context: Optional[dict]) -> str:
        """Build the prompt for the subagent."""
        prompt_parts = [f"**Task:** {task}"]

        if context:
            if isinstance(context, dict):
                context_str = json.dumps(context, indent=2)
                prompt_parts.append(f"\n**Context:**\n```json\n{context_str}\n```")
            else:
                prompt_parts.append(f"\n**Context:**\n{context}")

        prompt_parts.append("\nComplete this task and report your findings.")

        return "\n".join(prompt_parts)

    # --- ToolProvider Interface ---

    def get_definitions(self) -> list[dict]:
        """Get tool definitions."""
        return [SUBAGENT_TOOL]

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a tool (sync wrapper)."""
        if tool_name == "spawn_subagent":
            # Run async spawn in sync context
            # Use a thread pool to avoid conflicts with running event loops
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, self._execute_spawn(args))
                return future.result()
        return f"Unknown tool: {tool_name}"

    async def _execute_spawn(self, args: dict) -> str:
        """Execute spawn_subagent tool."""
        task = args.get("task", "")
        if not task:
            return "Error: task is required"

        # Parse context
        context = None
        context_str = args.get("context")
        if context_str:
            try:
                context = json.loads(context_str)
            except json.JSONDecodeError:
                # Use as plain text
                context = {"raw": context_str}

        # Get timeout
        timeout_minutes = args.get("timeout_minutes", 5)
        timeout_minutes = min(max(timeout_minutes, 1), 30)  # Clamp 1-30
        timeout_seconds = timeout_minutes * 60

        # Spawn subagent
        result = await self.spawn(
            task=task,
            context=context,
            timeout_seconds=timeout_seconds,
        )

        if result.success:
            return f"**Subagent completed** ({result.elapsed_seconds:.1f}s)\n\n{result.output}"
        else:
            return f"**Subagent failed:** {result.error}"

    @property
    def restart_requested(self) -> bool:
        """Check if restart was requested."""
        return self._restart_requested

    # --- CLI Commands ---

    def register_commands(self, cli) -> None:
        """Register subagent CLI commands."""
        plugin = self  # Capture for closures

        @cli.group()
        def subagent():
            """Subagent management commands."""
            pass

        @subagent.command("spawn")
        @click.argument("task")
        @click.option("--context", "-c", help="Context JSON or text")
        @click.option("--timeout", "-t", type=int, default=5, help="Timeout in minutes")
        def spawn_cmd(task: str, context: str, timeout: int):
            """Spawn an isolated subagent.

            TASK: Task description for the subagent
            """
            click.echo(f"Spawning subagent for: {task[:50]}...")

            # Parse context
            ctx = None
            if context:
                try:
                    ctx = json.loads(context)
                except json.JSONDecodeError:
                    ctx = {"raw": context}

            # Run spawn
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run,
                    plugin.spawn(task, context=ctx, timeout_seconds=timeout * 60),
                )
                result = future.result()

            if result.success:
                click.echo(f"\n✓ Completed in {result.elapsed_seconds:.1f}s\n")
                click.echo(result.output)
            else:
                click.echo(f"\n✗ Failed: {result.error}", err=True)

        @subagent.command("status")
        def status_cmd():
            """Show subagent status."""
            click.echo("\nSubagent Status:")
            click.echo("-" * 40)
            click.echo(
                f"  Active:         {plugin._active_count}/{plugin._max_concurrent}"
            )
            click.echo(f"  Max concurrent: {plugin._max_concurrent}")
            click.echo(f"  Default timeout: {plugin._default_timeout}s")
            click.echo(f"  Max timeout:    {plugin._max_timeout}s")
            click.echo()


def create_plugin() -> SubagentPlugin:
    """Factory function to create the plugin."""
    return SubagentPlugin()
