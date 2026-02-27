"""Cobot CLI - command line interface for the agent."""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

import click


# --- Config Utilities ---


def get_config_paths() -> tuple[Path, Path]:
    """Get home and local config paths."""
    home_config = Path.home() / ".cobot" / "cobot.yml"
    local_config = Path("cobot.yml")
    return home_config, local_config


def load_merged_config():
    """Load config with local overriding home."""
    from cobot.plugins.config import load_config

    return load_config()


# --- PID File ---


def get_pid_file() -> Path:
    """Get path to PID file."""
    return Path.home() / ".cobot" / "cobot.pid"


def read_pid() -> Optional[int]:
    """Read PID from file, return None if not found or stale."""
    pid_file = get_pid_file()
    if not pid_file.exists():
        return None

    try:
        pid = int(pid_file.read_text().strip())
        # Check if process exists
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError):
        # Stale PID file — clean it up
        pid_file.unlink(missing_ok=True)
        return None
    except PermissionError:
        # Process exists but owned by another user — treat as running
        return pid


def write_pid(pid: int) -> None:
    """Write PID to file."""
    pid_file = get_pid_file()
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def remove_pid() -> None:
    """Remove PID file."""
    pid_file = get_pid_file()
    if pid_file.exists():
        pid_file.unlink()


# --- CLI Groups ---


@click.group()
@click.version_option(version="0.1.0", prog_name="cobot")
def cli():
    """Cobot - Minimal self-sovereign AI agent."""
    pass


# --- Core Commands ---


@cli.command()
@click.option("--config", "-c", type=click.Path(exists=True), help="Config file path")
@click.option("--stdin", is_flag=True, help="Run in stdin mode (no Nostr)")
@click.option("--plugins", "-p", type=click.Path(exists=True), help="Plugins directory")
@click.option("--debug", "-d", is_flag=True, help="Enable debug logging")
@click.option(
    "--continue",
    "-C",
    "continue_session",
    is_flag=True,
    help="Continue previous conversation",
)
def run(
    config: Optional[str],
    stdin: bool,
    plugins: Optional[str],
    debug: bool,
    continue_session: bool,
):
    """Start the cobot agent."""
    # Check if already running
    existing_pid = read_pid()
    if existing_pid:
        click.echo(f"Cobot already running (PID {existing_pid})", err=True)
        click.echo("Use 'nano restart' to restart or kill the process first.", err=True)
        sys.exit(1)

    # Write our PID
    write_pid(os.getpid())

    try:
        from cobot import plugins as plugin_system
        from cobot.agent import Cobot
        import yaml

        # Load config file first (for plugin filtering)
        config_path = Path(config) if config else _find_config_path()
        raw_config = {}
        if config_path.exists():
            with open(config_path) as f:
                raw_config = yaml.safe_load(f) or {}

        # Override logger level if --debug flag
        if debug:
            if "logger" not in raw_config:
                raw_config["logger"] = {}
            raw_config["logger"]["level"] = "debug"

        # Persistence: disabled by default, --continue to enable
        # Also enable for stdin mode (interactive session needs history)
        if "persistence" not in raw_config:
            raw_config["persistence"] = {}
        if continue_session or stdin:
            raw_config["persistence"]["enabled"] = True
            if continue_session:
                click.echo("Continuing previous conversation", err=True)
        else:
            raw_config["persistence"]["enabled"] = False

        # Load plugins with config (async init)
        import asyncio

        # Reset registry (may have been populated by CLI command registration)
        plugin_system.reset_registry()

        plugins_dir = Path(plugins) if plugins else Path("cobot/plugins")
        if plugins_dir.exists():
            registry = asyncio.run(
                plugin_system.init_plugins(plugins_dir, config=raw_config)
            )
            click.echo(f"Loaded {len(registry)} plugin(s)", err=True)
        else:
            registry = plugin_system.get_registry()

        # Get config from plugin
        from cobot.plugins.config import get_config

        cfg = get_config()

        # Check API key from env or config
        ppq_config = cfg._raw.get("ppq", {})
        api_key = ppq_config.get("api_key") or os.environ.get("PPQ_API_KEY")
        if cfg.provider == "ppq" and not api_key:
            click.echo("Error: PPQ_API_KEY not set", err=True)
            sys.exit(1)

        bot = Cobot(registry)

        # Set up restart signal handler
        def handle_restart(signum, frame):
            click.echo("\nRestart signal received, restarting...", err=True)
            remove_pid()
            os.execv(sys.executable, [sys.executable] + sys.argv)

        signal.signal(signal.SIGUSR1, handle_restart)

        if stdin:
            bot.run_stdin_sync()
        else:
            bot.run_sync()
    finally:
        remove_pid()


@cli.command()
def restart():
    """Restart the running cobot agent."""
    pid = read_pid()
    if not pid:
        click.echo("Cobot is not running.", err=True)
        sys.exit(1)

    try:
        os.kill(pid, signal.SIGUSR1)
        click.echo(f"Restart signal sent to PID {pid}")
    except ProcessLookupError:
        click.echo("Process not found, removing stale PID file.", err=True)
        remove_pid()
        sys.exit(1)


@cli.command()
@click.option("--json", "as_json", is_flag=True, help="Output as JSON")
def status(as_json: bool):
    """Show cobot status."""
    pid = read_pid()

    status_data = {
        "running": pid is not None,
        "pid": pid,
    }

    if pid:
        # Get process info
        try:
            import time

            stat_file = Path(f"/proc/{pid}/stat")
            if stat_file.exists():
                # Get start time from /proc
                stat = stat_file.read_text().split()
                # Field 22 is starttime in clock ticks
                starttime_ticks = int(stat[21])
                clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
                uptime_file = Path("/proc/uptime")
                system_uptime = float(uptime_file.read_text().split()[0])
                process_start = system_uptime - (starttime_ticks / clock_ticks)
                status_data["uptime_seconds"] = int(
                    time.time() - (time.time() - process_start)
                )
        except Exception:
            status_data["uptime_seconds"] = None

        # Try to get wallet balance
        try:
            from cobot.plugins.config import load_config
            from cobot.plugins.wallet import Wallet

            config = load_config()
            wallet = Wallet(Path(config.paths.skills))
            status_data["wallet_balance"] = wallet.get_balance()
        except Exception:
            status_data["wallet_balance"] = None

    if as_json:
        click.echo(json.dumps(status_data, indent=2))
    else:
        click.echo("Cobot Status")
        click.echo("──────────────")
        if status_data["running"]:
            click.echo(f"State:    Running (PID {status_data['pid']})")
            if status_data.get("uptime_seconds"):
                hours, rem = divmod(status_data["uptime_seconds"], 3600)
                mins, secs = divmod(rem, 60)
                click.echo(f"Uptime:   {hours}h {mins}m")
            if status_data.get("wallet_balance") is not None:
                click.echo(f"Wallet:   {status_data['wallet_balance']:,} sats")
        else:
            click.echo("State:    Not running")


# --- Wallet Commands ---


@cli.group()
def wallet():
    """Wallet commands."""
    pass


@wallet.command("balance")
def wallet_balance():
    """Check wallet balance."""
    try:
        from cobot.plugins.config import load_config
        from cobot.plugins.wallet import Wallet

        config = load_config()
        w = Wallet(Path(config.paths.skills))
        balance = w.get_balance()
        click.echo(f"Balance: {balance:,} sats")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@wallet.command("address")
def wallet_address():
    """Show Lightning address."""
    try:
        from cobot.plugins.config import load_config
        from cobot.plugins.wallet import Wallet

        config = load_config()
        w = Wallet(Path(config.paths.skills))
        address = w.get_lightning_address()
        click.echo(f"Lightning address: {address}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@wallet.command("pay")
@click.argument("invoice")
def wallet_pay(invoice: str):
    """Pay a Lightning invoice."""
    try:
        from cobot.plugins.config import load_config
        from cobot.plugins.wallet import Wallet

        config = load_config()
        w = Wallet(Path(config.paths.skills))
        result = w.pay_invoice(invoice)
        if result.get("success"):
            click.echo("Payment successful!")
        else:
            click.echo(f"Payment failed: {result.get('error')}", err=True)
            sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# --- DM Commands ---


@cli.command("dm")
@click.argument("npub")
@click.argument("message")
def send_dm(npub: str, message: str):
    """Send a DM to an npub."""
    try:
        from cobot.plugins.config import load_config
        from cobot.plugins.nostr import NostrClient

        config = load_config()
        client = NostrClient(Path(config.paths.skills))
        event_id = client.send_dm(npub, message)
        click.echo(f"Sent! Event ID: {event_id}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("dms")
@click.option("--since", default="1h", help="Time window (e.g., 1h, 30m, 1d)")
def list_dms(since: str):
    """List recent DMs."""
    # Parse time
    minutes = 60  # default 1h
    if since.endswith("m"):
        minutes = int(since[:-1])
    elif since.endswith("h"):
        minutes = int(since[:-1]) * 60
    elif since.endswith("d"):
        minutes = int(since[:-1]) * 1440

    try:
        from cobot.plugins.config import load_config
        from cobot.plugins.nostr import NostrClient

        config = load_config()
        client = NostrClient(Path(config.paths.skills))
        client.get_identity()  # Populate own pubkey
        messages = client.check_dms(since_minutes=minutes)

        if not messages:
            click.echo("No messages.")
            return

        for msg in messages:
            sender_short = msg.sender[:16] + "..."
            content_short = msg.content[:50] + ("..." if len(msg.content) > 50 else "")
            click.echo(f"[{sender_short}] {content_short}")
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


# --- Config Commands ---


@cli.group()
def config():
    """Configuration commands."""
    pass


def _mask_secrets(data: dict, parent_key: str = "") -> dict:
    """Mask sensitive values in config dict."""
    secret_keys = {"api_key", "secret", "password", "token", "private_key"}
    result = {}
    for k, v in data.items():
        if isinstance(v, dict):
            result[k] = _mask_secrets(v, k)
        elif k in secret_keys and isinstance(v, str) and len(v) > 4:
            result[k] = f"***{v[-4:]}"
        else:
            result[k] = v
    return result


@config.command("show")
@click.option("--reveal", is_flag=True, help="Show secrets unmasked")
def config_show(reveal: bool):
    """Show current configuration.

    Keys shown can be used with 'config get/set' commands.
    Secrets are masked by default (use --reveal to show).
    """
    import yaml

    cfg = load_merged_config()

    # Get raw config and mask secrets
    data = cfg._raw.copy() if cfg._raw else {}

    if not reveal:
        data = _mask_secrets(data)

    if data:
        click.echo(yaml.dump(data, default_flow_style=False, sort_keys=False))
    else:
        click.echo("# No configuration loaded")
        click.echo("# Create ~/.cobot/cobot.yml or ./cobot.yml")

    click.echo("# Use 'cobot config get <key>' or 'cobot config set <key> <value>'")


@config.command("edit")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(),
    help="Config file to edit",
)
def config_edit(config_path: Optional[str]):
    """Edit config in $EDITOR."""
    editor = os.environ.get("EDITOR", "vi")
    path = _find_config_path(config_path)

    if not path.exists():
        # Create parent directory if needed
        path.parent.mkdir(parents=True, exist_ok=True)
        # Create default config
        path.write_text("""# Cobot Configuration
provider: ppq

identity:
  name: "MyAgent"

ppq:
  # api_key: "your-key-here"  # or set PPQ_API_KEY env var
  model: "openai/gpt-4o"

exec:
  enabled: true
  timeout: 30
""")
        click.echo(f"Created new config at {path}", err=True)

    subprocess.run([editor, str(path)])


def _find_config_path(explicit_path: Optional[str] = None) -> Path:
    """Find config file path (same logic as config loading)."""
    if explicit_path:
        return Path(explicit_path)

    # Check local first, then home
    local_config = Path("cobot.yml")
    if local_config.exists():
        return local_config

    home_config = Path.home() / ".cobot" / "cobot.yml"
    if home_config.exists():
        return home_config

    # Default to home config for new files
    return home_config


@config.command("set")
@click.argument("key")
@click.argument("value")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(),
    help="Config file (default: ~/.cobot/cobot.yml or ./cobot.yml)",
)
def config_set(key: str, value: str, config_path: Optional[str]):
    """Set a configuration value.

    KEY uses dot notation for nested values (e.g., ppq.model, exec.timeout).

    Examples:
        cobot config set ppq.model openai/gpt-4o-mini
        cobot config set exec.timeout 60
        cobot config set identity.name MyBot
    """
    import yaml

    path = _find_config_path(config_path)

    # Load existing config or start fresh
    if path.exists():
        with open(path) as f:
            cfg = yaml.safe_load(f) or {}
    else:
        cfg = {}

    # Parse value (try to interpret as int, float, bool, or keep as string)
    parsed_value: any = value
    if value.lower() == "true":
        parsed_value = True
    elif value.lower() == "false":
        parsed_value = False
    elif value.isdigit():
        parsed_value = int(value)
    else:
        try:
            parsed_value = float(value)
        except ValueError:
            parsed_value = value  # Keep as string

    # Navigate to nested key and set value
    keys = key.split(".")
    current = cfg
    for k in keys[:-1]:
        if k not in current:
            current[k] = {}
        elif not isinstance(current[k], dict):
            click.echo(f"Error: {k} is not a section, cannot set nested key", err=True)
            sys.exit(1)
        current = current[k]

    old_value = current.get(keys[-1])
    current[keys[-1]] = parsed_value

    # Write back
    with open(path, "w") as f:
        yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)

    if old_value is not None:
        click.echo(f"Updated {key}: {old_value} → {parsed_value}")
    else:
        click.echo(f"Set {key} = {parsed_value}")


@config.command("get")
@click.argument("key")
@click.option(
    "--config",
    "-c",
    "config_path",
    type=click.Path(),
    help="Config file (default: ~/.cobot/cobot.yml or ./cobot.yml)",
)
def config_get(key: str, config_path: Optional[str]):
    """Get a configuration value.

    KEY uses dot notation for nested values (e.g., ppq.model, exec.timeout).
    """
    import yaml

    path = _find_config_path(config_path)

    if not path.exists():
        click.echo(f"Config file not found: {path}", err=True)
        sys.exit(1)

    with open(path) as f:
        cfg = yaml.safe_load(f) or {}

    # Navigate to nested key
    keys = key.split(".")
    current = cfg
    for k in keys:
        if not isinstance(current, dict) or k not in current:
            click.echo(f"Key not found: {key}", err=True)
            sys.exit(1)
        current = current[k]

    click.echo(current)


@config.command("validate")
def config_validate():
    """Validate configuration."""
    try:
        cfg = load_merged_config()
        errors = []

        # Check provider-specific requirements
        if cfg.provider == "ppq":
            import os

            ppq_config = cfg.get_plugin_config("ppq")
            if not ppq_config.get("api_key") and not os.environ.get("PPQ_API_KEY"):
                errors.append("PPQ_API_KEY not set (required when provider=ppq)")

        if cfg.polling_interval < 5:
            errors.append("Polling interval too short (min 5s)")

        if errors:
            click.echo("Configuration errors:", err=True)
            for err in errors:
                click.echo(f"  - {err}", err=True)
            sys.exit(1)
        else:
            click.echo("Configuration is valid ✓")
    except Exception as e:
        click.echo(f"Error loading config: {e}", err=True)
        sys.exit(1)


# --- Dev Commands ---


@cli.command("test")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def run_tests(verbose: bool):
    """Run test suite."""
    cmd = [sys.executable, "-m", "pytest", "tests/"]
    if verbose:
        cmd.append("-v")
    subprocess.run(cmd)


def register_plugin_commands():
    """Load plugins and let them register CLI commands via extension point.

    Uses the cli.commands extension point - plugins that want to contribute
    CLI commands declare implements={"cli.commands": "register_commands"}.
    """
    try:
        from cobot.plugins import discover_plugins, PluginRegistry

        # Try to find plugins directory
        plugins_dir = None
        candidates = [
            Path("cobot/plugins"),
            Path(__file__).parent / "plugins",
        ]
        for candidate in candidates:
            if candidate.exists():
                plugins_dir = candidate
                break

        if not plugins_dir:
            return

        # Discover plugin classes (don't start them)
        plugin_classes = discover_plugins(plugins_dir)

        # Create a lightweight registry for CLI command registration
        registry = PluginRegistry()
        instances = []
        for plugin_class in plugin_classes:
            try:
                instance = plugin_class()
                instance._registry = registry
                registry.register(instance)
                instances.append(instance)
            except Exception:
                pass

        # Use extension point to register CLI commands
        for plugin_id, plugin, method_name in registry.get_implementations(
            "cli.commands"
        ):
            try:
                method = getattr(plugin, method_name)
                method(cli)
            except Exception:
                pass  # Ignore failures during CLI discovery
    except Exception:
        pass  # Plugins not available


# --- Setup Wizard (Core) ---


@cli.group()
def wizard():
    """Setup wizard and plugin configuration."""
    pass


@wizard.command()
@click.option(
    "--non-interactive", "-y", is_flag=True, help="Use defaults, don't prompt"
)
@click.option(
    "--home", is_flag=True, help="Create config in ~/.cobot/ instead of current dir"
)
@click.option(
    "--config", "-c", "config_path_opt", type=click.Path(), help="Config file path"
)
def init(non_interactive: bool, home: bool, config_path_opt: Optional[str]):
    """Initialize cobot configuration.

    Interactive wizard to set up cobot.yml with plugins and credentials.
    Plugins can extend the wizard via wizard_section() and wizard_configure().
    """
    import yaml

    if config_path_opt:
        config_path = Path(config_path_opt)
    elif home:
        config_path = Path.home() / ".cobot" / "cobot.yml"
    else:
        config_path = Path("cobot.yml")

    if config_path.exists() and not non_interactive:
        if not click.confirm(f"{config_path} already exists. Overwrite?"):
            click.echo("Aborted.")
            return

    click.echo("\n🤖 Cobot Setup Wizard\n")

    # --- Core Configuration (always present) ---

    config = {
        "provider": "ppq",
        "identity": {"name": "MyAgent"},
    }

    if non_interactive:
        # Use defaults for core config
        config["ppq"] = {
            "api_base": "https://api.ppq.ai/v1",
            # api_key from PPQ_API_KEY env var
            "model": "openai/gpt-4o",
        }
        config["exec"] = {"enabled": True, "timeout": 30}
    else:
        # Interactive core setup

        # Identity
        click.echo("📛 Identity\n")
        name = click.prompt("Agent name", default="MyAgent")
        config["identity"]["name"] = name

        # Provider
        click.echo("\n🧠 LLM Provider\n")
        provider = click.prompt(
            "Provider", type=click.Choice(["ppq", "ollama"]), default="ppq"
        )
        config["provider"] = provider

        if provider == "ppq":
            click.echo("\n  PPQ Configuration (api.ppq.ai)")
            api_key = click.prompt(
                "  API key (or use env var)",
                default="${PPQ_API_KEY}",
                show_default=True,
            )
            model = click.prompt("  Model", default="openai/gpt-4o")
            config["ppq"] = {
                "api_base": "https://api.ppq.ai/v1",
                # Note: ${VAR} doesn't expand in YAML - use env var directly or set value
                "model": model,
            }
            if api_key != "${PPQ_API_KEY}":
                config["ppq"]["api_key"] = api_key
        else:
            click.echo("\n  Ollama Configuration (local)")
            base_url = click.prompt("  URL", default="http://localhost:11434")
            model = click.prompt("  Model", default="qwen2.5:7b")
            config["ollama"] = {
                "base_url": base_url,
                "model": model,
            }

        # Tool execution
        click.echo("\n🔧 Tool Execution\n")
        exec_enabled = click.confirm("Enable shell command execution?", default=True)
        config["exec"] = {
            "enabled": exec_enabled,
            "timeout": 30,
        }

    # --- Plugin Configuration (via extension points) ---

    if not non_interactive:
        try:
            from cobot.plugins import discover_plugins

            # Find plugins directory
            plugins_dir = None
            for candidate in [Path("cobot/plugins"), Path(__file__).parent / "plugins"]:
                if candidate.exists():
                    plugins_dir = candidate
                    break

            if plugins_dir:
                wizard_plugins = []

                # Discover plugins that participate in wizard
                for plugin_class in discover_plugins(plugins_dir):
                    try:
                        plugin = plugin_class()
                        section = plugin.wizard_section()
                        if section:
                            wizard_plugins.append((plugin, section))
                    except Exception:
                        pass

                if wizard_plugins:
                    click.echo("\n🔌 Plugins\n")

                    for plugin, section in wizard_plugins:
                        key = section.get("key", plugin.meta.id)
                        name = section.get("name", plugin.meta.id)
                        desc = section.get("description", "")

                        prompt_text = f"Configure {name}?"
                        if desc:
                            prompt_text = f"Configure {name} ({desc})?"

                        if click.confirm(prompt_text, default=False):
                            try:
                                plugin_config = plugin.wizard_configure(config)
                                if plugin_config:
                                    config[key] = plugin_config
                                    click.echo(f"  ✓ {name} configured\n")
                            except Exception as e:
                                click.echo(
                                    f"  ✗ Error configuring {name}: {e}\n", err=True
                                )

        except Exception:
            # Plugins not available, skip plugin configuration
            pass

    # --- Write Configuration ---

    # Create parent directory if needed
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    click.echo(f"\n✅ Configuration written to {config_path}")
    click.echo("\nNext steps:")
    click.echo(f"  1. Review and edit {config_path}")
    click.echo("  2. Set environment variables (PPQ_API_KEY, etc.)")
    click.echo("  3. Run: cobot run")


@wizard.command()
def plugins():
    """List available plugins and their wizard sections."""
    try:
        from cobot.plugins import init_plugins, get_registry
        from pathlib import Path

        try:
            plugins_dir = Path(__file__).parent / "plugins"
            init_plugins(plugins_dir)
        except Exception as e:
            click.echo(f"Note: Could not fully initialize plugins: {e}", err=True)

        registry = get_registry()
        if not registry:
            click.echo("No plugin registry available.")
            return

        click.echo("\n📦 Plugins:\n")

        for plugin in registry.all_plugins():
            meta = plugin.meta
            caps = ", ".join(meta.capabilities) if meta.capabilities else "none"
            click.echo(f"  {meta.id} v{meta.version}")
            click.echo(f"    Capabilities: {caps}")
            if meta.extension_points:
                click.echo(f"    Extension points: {', '.join(meta.extension_points)}")

            # Show wizard section if available
            try:
                section = plugin.wizard_section()
                if section:
                    name = section.get("name", meta.id)
                    desc = section.get("description", "")
                    click.echo(f"    Wizard: {name}" + (f" - {desc}" if desc else ""))
            except Exception:
                pass

            click.echo()

    except Exception as e:
        click.echo(f"Error listing plugins: {e}", err=True)


def main():
    """Entry point."""
    # Let plugins register their commands
    register_plugin_commands()

    # Run CLI
    cli()


if __name__ == "__main__":
    main()
