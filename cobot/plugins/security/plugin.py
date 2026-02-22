"""Security plugin - blocks prompt injection attacks.

Priority: 10 (early, before other processing)
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta


class SecurityPlugin(Plugin):
    """Prompt injection detection plugin."""

    meta = PluginMeta(
        id="security",
        version="1.0.0",
        capabilities=["security"],
        dependencies=["config"],
        priority=10,
    )

    def __init__(self):
        self._shield_script: Optional[Path] = None
        self._use_llm: bool = True

    def configure(self, config: dict) -> None:
        # Get skills path from paths.skills or security.skills_path
        paths = config.get("paths", {})
        security_config = config.get("security", {})
        skills_dir = Path(
            security_config.get("skills_path") or paths.get("skills") or "./skills"
        )
        self._shield_script = (
            skills_dir / "prompt-injection-shield" / "scripts" / "classifier.py"
        )
        self._use_llm = security_config.get("use_llm_layer", True)

    async def start(self) -> None:
        if self._shield_script and self._shield_script.exists():
            self.log_info("Shield initialized")
        else:
            self.log_warn("Shield script not found")

    async def stop(self) -> None:
        pass

    def _check_injection(self, text: str) -> dict:
        """Check text for prompt injection."""
        if not self._shield_script or not self._shield_script.exists():
            return {"flagged": False, "reason": "shield_not_found"}

        try:
            cmd = ["python3", str(self._shield_script)]
            if self._use_llm:
                cmd.append("--llm")
            cmd.append(text)

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10,
                env={**os.environ, "PPQ_API_KEY": os.environ.get("PPQ_API_KEY", "")},
            )

            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"flagged": False, "reason": "parse_error"}
        except subprocess.TimeoutExpired:
            return {"flagged": False, "reason": "timeout"}
        except Exception as e:
            return {"flagged": False, "reason": str(e)}

    async def on_message_received(self, ctx: dict) -> dict:
        """Check incoming messages for injection."""
        message = ctx.get("message", "")
        if not message:
            return ctx

        result = self._check_injection(message)

        if result.get("flagged"):
            sender = ctx.get("sender", "")[:16]
            self.log_warn(f"⚠️ BLOCKED injection from {sender}...")
            ctx["abort"] = True
            ctx["abort_message"] = "Message blocked by security filter."

        return ctx


def create_plugin() -> SecurityPlugin:
    return SecurityPlugin()
