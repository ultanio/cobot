"""Pairing plugin - user authorization via pairing codes.

Priority: 5 (very early - before security, before everything)

When an unauthorized user sends a message:
1. Generate/retrieve a pairing code
2. Send them instructions
3. Abort message processing

Bot owners can approve via CLI:
  cobot pairing approve <code>
"""

import sys
from pathlib import Path
from typing import Optional

import click

from ..base import Plugin, PluginMeta
from .storage import PairingStorage


class PairingPlugin(Plugin):
    """User authorization via pairing codes."""

    meta = PluginMeta(
        id="pairing",
        version="1.0.0",
        capabilities=["pairing"],
        dependencies=["config"],
        priority=5,  # Very early - check auth before anything else
    )

    def __init__(self):
        self._enabled: bool = True
        self._owner_ids: dict[str, list[str]] = {}  # channel -> [user_ids]
        self._skip_channels: list[str] = []  # Channels to skip (no auth required)
        self._storage: Optional[PairingStorage] = None
        self._storage_path: Path = Path.home() / ".cobot" / "pairing.yml"
        self._comm = None  # Communication plugin reference

    def configure(self, config: dict) -> None:
        """Configure the pairing plugin.

        Config format:
            pairing:
              enabled: true
              owner_ids:
                telegram: ["769134210"]
                discord: ["123456789"]
              skip_channels: ["nostr"]  # No auth required for these
              storage_path: ~/.cobot/pairing.yml  # Optional
        """
        pairing_config = config.get("pairing", {})

        self._enabled = pairing_config.get("enabled", True)
        self._owner_ids = pairing_config.get("owner_ids", {})
        self._skip_channels = pairing_config.get("skip_channels", [])

        # Custom storage path
        if pairing_config.get("storage_path"):
            self._storage_path = Path(pairing_config["storage_path"]).expanduser()

    async def start(self) -> None:
        """Initialize storage and bootstrap owner_ids."""
        if not self._enabled:
            print("[pairing] Disabled", file=sys.stderr)
            return

        # Initialize storage
        self._storage = PairingStorage(self._storage_path)

        # Bootstrap owner_ids as authorized
        for channel, user_ids in self._owner_ids.items():
            for user_id in user_ids:
                self._storage.add_authorized(channel, str(user_id), f"owner:{user_id}")

        # Get communication plugin for sending responses
        try:
            registry = self._registry
            if registry:
                self._comm = registry.get("communication")
        except Exception:
            pass

        authorized_count = len(self._storage.get_authorized())
        pending_count = len(self._storage.get_pending())
        print(
            f"[pairing] Ready ({authorized_count} authorized, {pending_count} pending)",
            file=sys.stderr,
        )

    async def stop(self) -> None:
        """Clean up."""
        pass

    def _send_pairing_message(
        self, channel: str, channel_id: str, user_id: str, code: str
    ) -> None:
        """Send pairing instructions to user."""
        message = (
            f"Access not configured.\n"
            f"Your {channel.title()} user id: {user_id}\n"
            f"Pairing code: {code}\n\n"
            f"Ask the bot owner to approve with:\n"
            f"  cobot pairing approve {code}"
        )

        if self._comm:
            from ..communication import OutgoingMessage

            self._comm.send(
                OutgoingMessage(
                    channel_type=channel,
                    channel_id=channel_id,
                    content=message,
                )
            )
        else:
            # Fallback: just print it
            print(f"[pairing] {message}", file=sys.stderr)

    async def on_message_received(self, ctx: dict) -> dict:
        """Check if user is authorized."""
        if not self._enabled or not self._storage:
            return ctx

        channel = ctx.get("channel_type", "")
        user_id = str(ctx.get("sender_id", ""))
        user_name = ctx.get("sender", "unknown")
        channel_id = ctx.get("channel_id", "")

        if not channel or not user_id:
            return ctx

        # Skip channels that don't require auth
        if channel in self._skip_channels:
            return ctx

        # Check if authorized
        if self._storage.is_authorized(channel, user_id):
            return ctx

        # Not authorized - create/get pending request
        req = self._storage.add_pending(channel, user_id, user_name)

        # Send pairing message
        self._send_pairing_message(channel, channel_id, user_id, req.code)

        # Log
        print(
            f"[pairing] Unauthorized: {user_name} ({channel}:{user_id}) - code: {req.code}",
            file=sys.stderr,
        )

        # Abort processing
        ctx["abort"] = True
        return ctx

    # --- CLI Extension ---

    def register_commands(self, cli) -> None:
        """Register pairing CLI commands."""

        @cli.group()
        def pairing():
            """Manage user pairing and authorization."""
            pass

        @pairing.command("list")
        @click.option("--pending", is_flag=True, help="Show only pending requests")
        @click.option("--approved", is_flag=True, help="Show only approved users")
        def pairing_list(pending, approved):
            """List pairing requests and authorized users."""
            storage = PairingStorage(self._storage_path)

            if not approved:  # Show pending (default or --pending)
                pending_list = storage.get_pending()
                if pending_list:
                    click.echo("Pending requests:")
                    for req in pending_list:
                        click.echo(
                            f"  [{req.code}] {req.channel}:{req.user_id} ({req.name}) "
                            f"- {req.requested_at}"
                        )
                else:
                    click.echo("No pending requests.")

            if not pending:  # Show approved (default or --approved)
                if not approved:
                    click.echo()  # Blank line between sections

                authorized_list = storage.get_authorized()
                if authorized_list:
                    click.echo("Authorized users:")
                    for user in authorized_list:
                        click.echo(
                            f"  {user.channel}:{user.user_id} ({user.name}) "
                            f"- {user.approved_at}"
                        )
                else:
                    click.echo("No authorized users.")

        @pairing.command("approve")
        @click.argument("code")
        def pairing_approve(code):
            """Approve a pairing request."""
            storage = PairingStorage(self._storage_path)

            user = storage.approve(code)
            if user:
                click.echo(f"✓ Approved {user.name} ({user.channel}:{user.user_id})")
            else:
                click.echo(f"✗ Code not found: {code}", err=True)
                raise SystemExit(1)

        @pairing.command("reject")
        @click.argument("code")
        def pairing_reject(code):
            """Reject a pairing request."""
            storage = PairingStorage(self._storage_path)

            if storage.reject(code):
                click.echo(f"✓ Rejected request with code: {code}")
            else:
                click.echo(f"✗ Code not found: {code}", err=True)
                raise SystemExit(1)

        @pairing.command("revoke")
        @click.argument("channel")
        @click.argument("user_id")
        def pairing_revoke(channel, user_id):
            """Revoke a user's authorization."""
            storage = PairingStorage(self._storage_path)

            if storage.revoke(channel, user_id):
                click.echo(f"✓ Revoked {channel}:{user_id}")
            else:
                click.echo(f"✗ User not found: {channel}:{user_id}", err=True)
                raise SystemExit(1)

    # --- Setup Wizard Extension ---

    def wizard_section(self) -> dict | None:
        """Return wizard section info for pairing."""
        return {
            "key": "pairing",
            "name": "User Authorization",
            "description": "Control who can interact with the bot",
        }

    def wizard_configure(self, config: dict) -> dict:
        """Interactive pairing configuration for the setup wizard."""
        import click

        click.echo("\nUser authorization via pairing codes.")
        click.echo("Unknown users will need approval before chatting.\n")

        enabled = click.confirm("Enable pairing?", default=True)
        if not enabled:
            return {"enabled": False}

        # Owner IDs per channel
        owner_ids = {}
        click.echo("\nAdd owner IDs (always authorized, no pairing needed):")

        # Check if telegram is configured
        if "telegram" in config:
            if click.confirm("Add Telegram owner ID?", default=True):
                telegram_id = click.prompt("Your Telegram user ID")
                owner_ids["telegram"] = [telegram_id]

        # Generic channel
        while click.confirm("Add owner ID for another channel?", default=False):
            channel = click.prompt("Channel name (e.g., discord, nostr)")
            user_id = click.prompt(f"Your {channel} user ID")
            if channel not in owner_ids:
                owner_ids[channel] = []
            owner_ids[channel].append(user_id)

        # Skip channels
        skip_channels = []
        if click.confirm("Skip pairing for any channels?", default=False):
            channels = click.prompt(
                "Channels to skip (comma-separated)", default="nostr"
            )
            skip_channels = [c.strip() for c in channels.split(",")]

        result = {"enabled": True}
        if owner_ids:
            result["owner_ids"] = owner_ids
        if skip_channels:
            result["skip_channels"] = skip_channels

        return result


def create_plugin() -> PairingPlugin:
    """Factory function."""
    return PairingPlugin()
