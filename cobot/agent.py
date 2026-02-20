#!/usr/bin/env python3
"""Cobot - Minimal self-sovereign AI agent.

The agent is a loop runner. All logic lives in plugins.
Plugins with capability "loop" are run concurrently via asyncio.gather.
"""

import asyncio
import sys


class Cobot:
    """Main agent class — runs all loop plugins concurrently."""

    def __init__(self, registry):
        self.registry = registry

    async def run(self) -> None:
        """Run all loop plugins concurrently.

        Each plugin with capability "loop" gets its run() called.
        They execute in parallel via asyncio.gather.
        """
        loops = self.registry.all_with_capability("loop")

        if not loops:
            print("Error: No loop plugins registered", file=sys.stderr)
            return

        print(
            f"Starting {len(loops)} loop(s): " + ", ".join(p.meta.id for p in loops),
            file=sys.stderr,
        )

        try:
            await asyncio.gather(*[loop.run() for loop in loops])
        except asyncio.CancelledError:
            pass
        finally:
            await self.registry.stop_all()

    def run_sync(self) -> None:
        """Synchronous wrapper for run()."""
        asyncio.run(self.run())

    # --- Stdin mode (for testing/development) ---

    async def run_stdin(self) -> None:
        """Interactive stdin mode — sends input to the first loop plugin."""
        loop_plugin = self.registry.all_with_capability("loop")
        if not loop_plugin:
            print("Error: No loop plugins registered", file=sys.stderr)
            return

        loop = loop_plugin[0]
        print("Cobot ready. Type a message (Ctrl+D to exit):", file=sys.stderr)

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break

                message = line.decode().strip()
                if not message:
                    continue

                # Use the loop's respond method if available
                if hasattr(loop, "_respond"):
                    response = await loop._respond(message, sender="stdin")
                    print(response)
                else:
                    print(f"[{loop.meta.id}] No _respond method", file=sys.stderr)
        except asyncio.CancelledError:
            pass
        finally:
            await self.registry.stop_all()

    def run_stdin_sync(self) -> None:
        """Synchronous wrapper for run_stdin()."""
        asyncio.run(self.run_stdin())
