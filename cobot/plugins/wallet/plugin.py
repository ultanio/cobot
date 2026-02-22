"""Wallet plugin - Lightning wallet via npub.cash.

Priority: 25 (after config)
Capability: wallet
"""

import os
import subprocess
from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta
from ..interfaces import WalletProvider, WalletError


class WalletPlugin(Plugin, WalletProvider):
    """Cashu Lightning wallet via npub.cash skill scripts."""

    meta = PluginMeta(
        id="wallet",
        version="1.0.0",
        capabilities=["wallet"],
        dependencies=["config"],
        priority=25,
    )

    def __init__(self):
        self._config: dict = {}
        self._scripts_dir: Optional[Path] = None
        self._env: dict = {}

    def configure(self, config: dict) -> None:
        """Receive wallet configuration."""
        self._config = config

        # Get skills path from paths.skills or wallet.skills_path
        paths = config.get("paths", {})
        wallet_config = config.get("wallet", {})
        skills_path = (
            wallet_config.get("skills_path") or paths.get("skills") or "./skills"
        )
        self._scripts_dir = Path(skills_path) / "npubcash" / "scripts"

        self._env = os.environ.copy()
        self._env["NODE_PATH"] = "/usr/lib/node_modules"

    async def start(self) -> None:
        """Check wallet availability."""
        if self._scripts_dir and self._scripts_dir.exists():
            self.log_info(f"Initialized from {self._scripts_dir}")
        else:
            self.log_warn(f"Scripts not found at {self._scripts_dir}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def _run_script(self, script_name: str, args: list = None) -> str:
        """Run a wallet skill script."""
        if not self._scripts_dir:
            raise WalletError("Wallet not configured")

        script_path = self._scripts_dir / script_name
        if not script_path.exists():
            raise WalletError(f"Script not found: {script_path}")

        cmd = ["node", str(script_path)] + (args or [])

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=self._env,
                timeout=30,
            )
            if result.returncode != 0:
                raise WalletError(f"Script failed: {result.stderr}")
            return result.stdout
        except subprocess.TimeoutExpired:
            raise WalletError("Script timed out")

    # --- WalletProvider Interface ---

    def get_balance(self) -> int:
        """Get wallet balance in sats."""
        output = self._run_script("balance.js")

        for line in output.split("\n"):
            if "balance:" in line.lower():
                parts = line.split(":")
                if len(parts) >= 2:
                    try:
                        return int(parts[-1].strip().split()[0])
                    except ValueError:
                        pass
        return 0

    def pay(self, invoice: str) -> dict:
        """Pay a Lightning invoice."""
        try:
            output = self._run_script("melt.js", [invoice])
            return {"success": True, "output": output.strip()}
        except WalletError as e:
            return {"success": False, "error": str(e)}

    def get_receive_address(self) -> str:
        """Get Lightning address."""
        output = self._run_script("info.js")

        for line in output.split("\n"):
            if "@npub.cash" in line:
                for part in line.split():
                    if "@npub.cash" in part:
                        return part.strip()
        return ""


# Factory function
def create_plugin() -> WalletPlugin:
    return WalletPlugin()
