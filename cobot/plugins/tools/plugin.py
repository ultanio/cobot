"""Tools plugin - provides tool execution for the agent.

Priority: 30 (after config, llm)
Capability: tools
"""

import os
import re
import subprocess
import sys
from pathlib import Path

from ..base import Plugin, PluginMeta
from ..interfaces import ToolProvider


# Tool definitions for LLM
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file (creates or overwrites)",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to edit"},
                    "old_text": {"type": "string", "description": "Exact text to find"},
                    "new_text": {
                        "type": "string",
                        "description": "Text to replace with",
                    },
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to run",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 30)",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restart_self",
            "description": "Restart the cobot process",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallet_balance",
            "description": "Check wallet balance in sats",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallet_pay",
            "description": "Pay a Lightning invoice",
            "parameters": {
                "type": "object",
                "properties": {
                    "invoice": {
                        "type": "string",
                        "description": "BOLT11 Lightning invoice",
                    }
                },
                "required": ["invoice"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wallet_receive",
            "description": "Get Lightning address to receive payments",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class ToolsPlugin(Plugin, ToolProvider):
    """Tool execution plugin."""

    meta = PluginMeta(
        id="tools",
        version="1.0.0",
        capabilities=["tools"],
        dependencies=["config"],
        priority=30,
    )

    # Protected paths that cannot be modified
    PROTECTED_PATHS = [
        "cobot/agent.py",
        "cobot/plugins/base.py",
        "cobot/plugins/registry.py",
        "cobot/plugins/interfaces.py",
        "cobot/plugins/config/plugin.py",
        "cobot/plugins/ppq/plugin.py",
        "cobot/plugins/ollama/plugin.py",
        "cobot/plugins/nostr/plugin.py",
        "cobot/plugins/tools/plugin.py",
    ]

    def __init__(self):
        self._config: dict = {}
        self._base_dir: Path = Path.cwd()
        self._exec_enabled: bool = True
        self._exec_allowlist: list[str] = []
        self._exec_blocklist: list[str] = []
        self._exec_timeout: int = 30
        self._context_budget: int = 64000
        self._restart_requested: bool = False

    def configure(self, config: dict) -> None:
        """Receive tools configuration."""
        exec_config = config.get("exec", {})
        self._exec_enabled = exec_config.get("enabled", True)
        self._exec_allowlist = exec_config.get("allowlist", [])
        self._exec_blocklist = exec_config.get("blocklist", [])
        self._exec_timeout = exec_config.get("timeout", 30)

    async def start(self) -> None:
        """Tools plugin is ready."""
        print(
            f"[Tools] Initialized, exec={'enabled' if self._exec_enabled else 'disabled'}",
            file=sys.stderr,
        )

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    # --- ToolProvider Interface ---

    def get_definitions(self) -> list[dict]:
        """Get tool definitions for LLM."""
        return TOOL_DEFINITIONS

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a tool by name."""
        executors = {
            "read_file": self._read_file,
            "write_file": self._write_file,
            "edit_file": self._edit_file,
            "exec": self._exec,
            "restart_self": self._restart_self,
            "wallet_balance": self._wallet_balance,
            "wallet_pay": self._wallet_pay,
            "wallet_receive": self._wallet_receive,
        }

        executor = executors.get(tool_name)
        if not executor:
            return f"Error: Unknown tool '{tool_name}'"

        try:
            return executor(**args)
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"

    @property
    def restart_requested(self) -> bool:
        return self._restart_requested

    # --- Tool Implementations ---

    def _is_protected(self, path: Path) -> bool:
        """Check if path is protected."""
        try:
            rel = path.resolve().relative_to(self._base_dir.resolve())
            return str(rel) in self.PROTECTED_PATHS
        except ValueError:
            return False

    def _is_exec_allowed(self, command: str) -> tuple[bool, str]:
        """Check if command is allowed."""
        if not self._exec_enabled:
            return False, "exec is disabled"

        for pattern in self._exec_blocklist:
            if re.search(pattern, command):
                return False, f"blocked by pattern: {pattern}"

        if self._exec_allowlist:
            for pattern in self._exec_allowlist:
                if re.search(pattern, command):
                    return True, "matched allowlist"
            return False, "not in allowlist"

        return True, "allowed"

    def _read_file(self, path: str) -> str:
        resolved = Path(path).expanduser().resolve()

        if not resolved.exists():
            return f"Error: File not found: {path}"
        if not resolved.is_file():
            return f"Error: Not a file: {path}"

        try:
            content = resolved.read_text()
            if len(content) > self._context_budget:
                return content[: self._context_budget] + "\n\n[truncated]"
            return content
        except Exception as e:
            return f"Error: {e}"

    def _write_file(self, path: str, content: str) -> str:
        resolved = Path(path).expanduser().resolve()

        if self._is_protected(resolved):
            return f"Error: Protected path: {path}"

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)
            resolved.write_text(content)
            return f"Successfully wrote {len(content)} bytes to {path}"
        except Exception as e:
            return f"Error: {e}"

    def _edit_file(self, path: str, old_text: str, new_text: str) -> str:
        resolved = Path(path).expanduser().resolve()

        if self._is_protected(resolved):
            return f"Error: Protected path: {path}"
        if not resolved.exists():
            return f"Error: File not found: {path}"

        try:
            content = resolved.read_text()
            if old_text not in content:
                return f"Error: Text not found in {path}"
            if content.count(old_text) > 1:
                return "Error: Text found multiple times - be more specific"

            resolved.write_text(content.replace(old_text, new_text))
            return f"Successfully edited {path}"
        except Exception as e:
            return f"Error: {e}"

    def _exec(self, command: str, timeout: int = None) -> str:
        timeout = timeout or self._exec_timeout

        allowed, reason = self._is_exec_allowed(command)
        if not allowed:
            return f"Error: {reason}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
            )

            output = result.stdout
            if result.stderr:
                output += f"\n[stderr]: {result.stderr}"
            if result.returncode != 0:
                output += f"\n[exit code: {result.returncode}]"

            if len(output) > self._context_budget // 2:
                output = output[: self._context_budget // 2] + "\n[truncated]"

            return output or "(no output)"
        except subprocess.TimeoutExpired:
            return f"Error: Timed out after {timeout}s"

    def _restart_self(self) -> str:
        self._restart_requested = True
        return "Restart requested."

    def _wallet_balance(self) -> str:
        wallet = self._get_wallet()
        if not wallet:
            return "Error: Wallet not available"
        try:
            return f"Balance: {wallet.get_balance()} sats"
        except Exception as e:
            return f"Error: {e}"

    def _wallet_pay(self, invoice: str) -> str:
        wallet = self._get_wallet()
        if not wallet:
            return "Error: Wallet not available"
        try:
            result = wallet.pay(invoice)
            return (
                "Payment successful"
                if result.get("success")
                else f"Failed: {result.get('error')}"
            )
        except Exception as e:
            return f"Error: {e}"

    def _wallet_receive(self) -> str:
        wallet = self._get_wallet()
        if not wallet:
            return "Error: Wallet not available"
        try:
            return f"Address: {wallet.get_receive_address()}"
        except Exception as e:
            return f"Error: {e}"

    def _get_wallet(self):
        """Get wallet plugin from registry."""
        if self._registry:
            return self._registry.get_by_capability("wallet")
        return None


# Factory function for plugin discovery
def create_plugin() -> ToolsPlugin:
    return ToolsPlugin()
