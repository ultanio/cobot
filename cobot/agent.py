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
            # Check if there are any plugins at all (headless mode)
            all_plugins = self.registry.all_plugins()
            if not all_plugins:
                print("Error: No plugins registered", file=sys.stderr)
                return

            print(
                "Running in headless mode (no loop plugins)",
                file=sys.stderr,
            )
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await self.registry.stop_all()
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
        """Interactive stdin mode — sends input to the first loop plugin.

        Also runs background tasks (cron scheduler, etc.) concurrently.
        """
        loop_plugin = self.registry.all_with_capability("loop")
        if not loop_plugin:
            print(
                "Stdin mode requires a loop plugin. None registered.",
                file=sys.stderr,
            )
            return

        loop = loop_plugin[0]
        print("Cobot ready. Type a message (Ctrl+D to exit):", file=sys.stderr)

        # Re-start plugins in this event loop (they were started in a different loop)
        await self.registry.restart_all()

        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        async def stdin_loop():
            """Handle stdin messages."""
            try:
                while True:
                    line = await reader.readline()
                    if not line:
                        break

                    message = line.decode().strip()
                    if not message:
                        continue

                    # Call on_message extension point (saves user message)
                    ctx = await loop.call_extension_chain(
                        "loop.on_message",
                        {
                            "message": message,
                            "sender": "stdin",
                            "sender_id": "stdin",
                            "channel_type": "stdin",
                            "channel_id": "stdin",
                            "event_id": f"stdin-{id(line)}",
                        },
                    )
                    if ctx.get("abort"):
                        continue

                    # Get response
                    if hasattr(loop, "_respond"):
                        response = await loop._respond(
                            ctx.get("message", message),
                            sender="stdin",
                            channel_type="stdin",
                            channel_id="stdin",
                        )
                        print(response)

                        # Call after_send extension point (saves assistant message)
                        await loop.call_extension_chain(
                            "loop.after_send",
                            {
                                "text": response,
                                "recipient": "stdin",
                                "channel_type": "stdin",
                                "channel_id": "stdin",
                            },
                        )
                    else:
                        print(f"[{loop.meta.id}] No _respond method", file=sys.stderr)
            except asyncio.CancelledError:
                pass

        async def poll_loop():
            """Poll for cron/injected messages in the background."""
            try:
                while True:
                    # Check for cancellation before expensive work
                    await asyncio.sleep(0)

                    # Poll extension point for injected messages
                    injected = await loop.call_extension("session.poll_messages")
                    for msg_list in injected:
                        if isinstance(msg_list, list):
                            for msg in msg_list:
                                if hasattr(loop, "_respond"):
                                    response = await loop._respond(
                                        msg.content,
                                        sender=msg.sender_name,
                                        channel_type=msg.channel_type,
                                        channel_id=msg.channel_id,
                                    )
                                    # Build output atomically, handle IO errors on shutdown
                                    try:
                                        output = (
                                            f"\n[Cron: {msg.channel_id}] {response}"
                                        )
                                        print(output, flush=True)
                                    except (BlockingIOError, BrokenPipeError, OSError):
                                        # stdout closed during shutdown, exit cleanly
                                        return
                    await asyncio.sleep(30)  # Poll every 30 seconds
            except asyncio.CancelledError:
                pass

        try:
            # Run stdin and poll loops concurrently
            # When stdin finishes (Ctrl+D), cancel poll_loop to avoid
            # BlockingIOError on print during shutdown
            stdin_task = asyncio.create_task(stdin_loop())
            poll_task = asyncio.create_task(poll_loop())

            # Wait for stdin to finish (user pressed Ctrl+D)
            await stdin_task

            # Cancel poll_loop cleanly
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        finally:
            await self.registry.stop_all()

    def run_stdin_sync(self) -> None:
        """Synchronous wrapper for run_stdin()."""
        asyncio.run(self.run_stdin())
