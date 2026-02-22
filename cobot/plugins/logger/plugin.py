"""Logger plugin - logs lifecycle events via extension points.

Priority: 5 (very early, logs everything)
"""

import json
import os
import sys

from ..base import Plugin, PluginMeta

# Column width for source names (aligns log output)
SOURCE_WIDTH = 12


# ANSI color codes
class Colors:
    """ANSI escape codes for colored terminal output."""

    RESET = "\033[0m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    RED = "\033[31m"
    GRAY = "\033[90m"

    @classmethod
    def supports_color(cls) -> bool:
        """Check if the terminal supports colors."""
        # Respect NO_COLOR env var (https://no-color.org/)
        if os.environ.get("NO_COLOR"):
            return False
        # Check if stderr is a TTY
        if not hasattr(sys.stderr, "isatty"):
            return False
        return sys.stderr.isatty()


class LoggerPlugin(Plugin):
    """Logging plugin for lifecycle events."""

    meta = PluginMeta(
        id="logger",
        version="1.0.0",
        capabilities=["logging"],
        dependencies=[],
        priority=5,
        implements={
            "loop.on_message": "log_message_received",
            "loop.before_llm": "log_before_llm",
            "loop.after_llm": "log_after_llm",
            "loop.before_tool": "log_before_tool",
            "loop.after_tool": "log_after_tool",
            "loop.after_send": "log_after_send",
            "loop.on_error": "log_error",
        },
    )

    def __init__(self):
        self._level: str = "info"
        self._levels = {"debug": 0, "info": 1, "warn": 2, "error": 3}
        self._colors_enabled: bool = Colors.supports_color()

    def configure(self, config: dict) -> None:
        logger_config = config.get("logger", {})
        self._level = logger_config.get("level", "info")
        # Allow explicit color override in config
        if "color" in logger_config:
            self._colors_enabled = logger_config["color"]

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def _should_log(self, level: str) -> bool:
        return self._levels.get(level, 1) >= self._levels.get(self._level, 1)

    def _colorize(self, level: str, text: str) -> str:
        """Apply color to log level indicator."""
        if not self._colors_enabled:
            return text

        level_colors = {
            "I": Colors.GREEN,
            "W": Colors.YELLOW,
            "E": Colors.RED,
            "D": Colors.GRAY,
        }
        color = level_colors.get(level, "")
        if color:
            return f"{color}{text}{Colors.RESET}"
        return text

    def _log(self, level: str, source: str, msg: str, **extra):
        if not self._should_log(level):
            return
        level_char = level[0].upper()
        level_str = self._colorize(level_char, f"[{level_char}]")
        source_padded = source.ljust(SOURCE_WIDTH)[:SOURCE_WIDTH]
        parts = [level_str, f"[{source_padded}]", msg]
        if extra:
            parts.append(json.dumps(extra, default=str))
        print(" ".join(parts), file=sys.stderr, flush=True)

    def log(self, level: str, source: str, msg: str, **extra):
        """Central logging method called by other plugins."""
        self._log(level, source, msg, **extra)

    # --- Extension Point Implementations ---

    async def log_message_received(self, ctx: dict) -> dict:
        msg = ctx.get("message", "")[:50]
        sender = ctx.get("sender", "")[:16]
        self._log("info", "msg_recv", f"From {sender}...", content=msg)
        return ctx

    async def log_before_llm(self, ctx: dict) -> dict:
        model = ctx.get("model", "")
        messages = ctx.get("messages", [])
        sys_prompt = ""
        for m in messages:
            if m.get("role") == "system":
                sys_prompt = m.get("content", "")[:200]
                break
        self._log("debug", "llm_call", f"Calling {model} ({len(messages)} msgs)")
        if sys_prompt:
            self._log("debug", "llm_call", f"System: {sys_prompt}...")
        return ctx

    async def log_after_llm(self, ctx: dict) -> dict:
        tokens_in = ctx.get("tokens_in", 0)
        tokens_out = ctx.get("tokens_out", 0)
        self._log("info", "llm_done", f"Tokens: {tokens_in}→{tokens_out}")
        return ctx

    async def log_before_tool(self, ctx: dict) -> dict:
        tool = ctx.get("tool", "")
        args = ctx.get("args", {})
        if tool == "read_file":
            detail = args.get("path", "?")
        elif tool == "write_file":
            path = args.get("path", "?")
            content_len = len(args.get("content", ""))
            detail = f"{path} ({content_len} chars)"
        elif tool == "edit_file":
            path = args.get("path", "?")
            old_text = args.get("old_text", "")[:30]
            detail = f"{path} ('{old_text}...')"
        elif tool == "exec":
            cmd = args.get("command", "?")
            detail = cmd[:80] + ("..." if len(cmd) > 80 else "")
        else:
            detail = str(list(args.values())[0])[:60] if args else ""
        self._log("info", "tool", f"{tool}: {detail}")
        return ctx

    async def log_after_tool(self, ctx: dict) -> dict:
        tool = ctx.get("tool", "")
        result = ctx.get("result", "")
        if len(result) > 100:
            result_preview = result[:100] + f"... ({len(result)} chars)"
        else:
            result_preview = result
        result_preview = result_preview.replace("\n", "\\n")
        self._log("info", "tool_done", f"{tool} → {result_preview}")
        return ctx

    async def log_after_send(self, ctx: dict) -> dict:
        recipient = ctx.get("recipient", "")[:16]
        self._log("info", "send", f"Sent to {recipient}...")
        return ctx

    async def log_error(self, ctx: dict) -> dict:
        error = ctx.get("error", "")
        hook = ctx.get("hook", "")
        self._log("error", "error", f"In {hook}: {error}")
        return ctx


def create_plugin() -> LoggerPlugin:
    return LoggerPlugin()
