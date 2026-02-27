"""Config plugin - loads and provides configuration.

Priority: 01 (very early, provides config to other plugins)
"""

import os
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Any

import yaml

from ..base import Plugin, PluginMeta


def _expand_env_vars(value: Any) -> Any:
    """Recursively expand ${VAR} and ${VAR:-default} in strings."""
    if isinstance(value, str):
        pattern = r"\$\{([^}:]+)(?::-([^}]*))?\}"

        def replacer(match):
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            elif default is not None:
                return default
            else:
                return ""

        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(v) for v in value]
    else:
        return value


@dataclass
class CobotConfig:
    """Parsed configuration object."""

    # Which plugins are enabled
    enabled_plugins: list[str] = field(default_factory=list)
    disabled_plugins: list[str] = field(default_factory=list)

    # LLM provider selection
    provider: str = "ppq"

    # Core settings
    identity_name: str = "Cobot"
    polling_interval: int = 30

    # Paths
    skills_path: Path = field(default_factory=lambda: Path("./skills"))
    memory_path: Path = field(default_factory=lambda: Path("./memory"))
    plugins_path: Path = field(default_factory=lambda: Path("./cobot/plugins"))
    soul_path: Path = field(default_factory=lambda: Path("./SOUL.md"))

    # Exec settings
    exec_enabled: bool = True
    exec_allowlist: list[str] = field(default_factory=list)
    exec_blocklist: list[str] = field(default_factory=list)
    exec_timeout: int = 30

    # Config directory (where cobot.yml lives)
    config_dir: Path = field(default_factory=lambda: Path.home() / ".cobot")

    # Raw config for plugin access
    _raw: dict = field(default_factory=dict)

    def get_plugin_config(self, plugin_id: str) -> dict:
        """Get config section for a specific plugin."""
        return self._raw.get(plugin_id, {})

    @classmethod
    def from_dict(cls, data: dict) -> "CobotConfig":
        """Create config from dictionary."""
        data = _expand_env_vars(data)

        # Parse plugins section
        plugins_section = data.get("plugins", {})
        enabled = plugins_section.get("enabled", [])
        disabled = plugins_section.get("disabled", [])

        # Parse identity
        identity = data.get("identity", {})

        # Parse polling
        polling = data.get("polling", {})

        # Parse paths
        paths = data.get("paths", {})

        # Parse exec
        exec_config = data.get("exec", {})

        return cls(
            enabled_plugins=enabled,
            disabled_plugins=disabled,
            provider=data.get("provider", "ppq"),
            identity_name=identity.get("name", "Cobot"),
            polling_interval=polling.get("interval_seconds", 30),
            skills_path=Path(paths.get("skills", "./skills")),
            memory_path=Path(paths.get("memory", "./memory")),
            plugins_path=Path(paths.get("plugins", "./cobot/plugins")),
            soul_path=Path(paths.get("soul", "./SOUL.md")),
            exec_enabled=exec_config.get("enabled", True),
            exec_allowlist=exec_config.get("allowlist", []),
            exec_blocklist=exec_config.get("blocklist", []),
            exec_timeout=exec_config.get("timeout", 30),
            _raw=data,
        )

    @classmethod
    def load(cls, path: Path) -> "CobotConfig":
        """Load config from YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        config = cls.from_dict(data)
        config.config_dir = path.parent.resolve()
        return config


class ConfigPlugin(Plugin):
    """Configuration management plugin."""

    meta = PluginMeta(
        id="config",
        version="1.0.0",
        capabilities=["config"],
        dependencies=[],
        priority=1,  # Load first
    )

    def __init__(self):
        self._config: Optional[CobotConfig] = None
        self._config_path: Optional[Path] = None

    def configure(self, config: dict) -> None:
        """Config plugin configures itself by loading the config file."""
        # Find and load config file
        self._config = self._load_config_file()

    async def start(self) -> None:
        """Config is already loaded in configure()."""
        if self._config:
            if self._config_path:
                self.log_info(f"Loaded from: {self._config_path.resolve()}")
            else:
                self.log_info("Using defaults (no config file found)")
            self.log_info(f"Provider: {self._config.provider}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    def _load_config_file(self) -> CobotConfig:
        """Load configuration from file(s)."""
        config = CobotConfig()

        # Try home directory config
        home_config = Path.home() / ".cobot" / "cobot.yml"
        if home_config.exists():
            config = CobotConfig.load(home_config)
            self._config_path = home_config

        # Try local cobot.yml (overrides home)
        local_config = Path("cobot.yml")
        if local_config.exists():
            config = CobotConfig.load(local_config)
            self._config_path = local_config

        # Legacy: try config.yaml (only if no other config found)
        legacy_config = Path("config.yaml")
        if legacy_config.exists() and self._config_path is None:
            config = CobotConfig.load(legacy_config)
            self._config_path = legacy_config

        return config

    def get_config(self) -> CobotConfig:
        """Get the loaded configuration."""
        if self._config is None:
            self._config = self._load_config_file()
        return self._config

    def get_plugin_config(self, plugin_id: str) -> dict:
        """Get config section for a specific plugin."""
        if self._config is None:
            return {}
        return self._config.get_plugin_config(plugin_id)


# Factory function for plugin discovery
def create_plugin() -> ConfigPlugin:
    return ConfigPlugin()
