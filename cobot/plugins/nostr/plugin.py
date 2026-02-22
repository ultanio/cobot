"""Nostr plugin - communication via Nostr protocol.

Priority: 25 (after config)
Capability: communication
"""

import os
import time
import uuid
from typing import Optional

from pynostr.key import PrivateKey, PublicKey
from pynostr.relay_manager import RelayManager
from pynostr.filters import FiltersList, Filters
from pynostr.event import EventKind
from pynostr.encrypted_dm import EncryptedDirectMessage

from ..base import Plugin, PluginMeta
from ..interfaces import CommunicationProvider, Message, CommunicationError


DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://relay.primal.net",
    "wss://nos.lol",
    "wss://relay.nostr.band",
    "wss://nostr.wine",
    "wss://nostr.mom",
]


class NostrPlugin(Plugin, CommunicationProvider):
    """Nostr communication plugin using pynostr."""

    meta = PluginMeta(
        id="nostr",
        version="1.0.0",
        capabilities=["communication"],
        dependencies=["config"],
        priority=25,
    )

    def __init__(self):
        self._config: dict = {}
        self._nsec: Optional[str] = None
        self._relays: list[str] = DEFAULT_RELAYS
        self._private_key: Optional[PrivateKey] = None
        self._public_key: Optional[PublicKey] = None

    def configure(self, config: dict) -> None:
        """Receive nostr-specific configuration."""
        self._config = config
        nostr_config = config.get("nostr", {})

        # Try to load nsec from: env var, config, or identity file
        self._nsec = os.environ.get("NOSTR_NSEC")
        if not self._nsec:
            self._nsec = nostr_config.get("nsec")
        if not self._nsec:
            identity_file = nostr_config.get("identity_file")
            if identity_file:
                import json
                from pathlib import Path

                try:
                    with open(Path(identity_file)) as f:
                        identity = json.load(f)
                        self._nsec = identity.get("nsec")
                except Exception as e:
                    self.log_error(f"Failed to load identity file: {e}")

        self._relays = nostr_config.get("relays", DEFAULT_RELAYS)

    async def start(self) -> None:
        """Initialize Nostr keys."""
        if not self._nsec:
            self.log_warn("NOSTR_NSEC not set, Nostr disabled")
            return

        try:
            if self._nsec.startswith("nsec"):
                self._private_key = PrivateKey.from_nsec(self._nsec)
            else:
                self._private_key = PrivateKey(bytes.fromhex(self._nsec))

            self._public_key = self._private_key.public_key
            self.log_info(f"Identity: {self._public_key.bech32()[:20]}...")
        except Exception as e:
            self.log_error(f"Failed to initialize: {e}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    # --- CommunicationProvider Interface ---

    def get_identity(self) -> dict:
        """Get own Nostr identity."""
        if not self._public_key:
            return {}
        return {
            "npub": self._public_key.bech32(),
            "hex": self._public_key.hex(),
        }

    def receive(self, since_minutes: int = 5) -> list[Message]:
        """Check for new DMs."""
        if not self._private_key:
            return []

        since_ts = int(time.time()) - (since_minutes * 60)

        relay_manager = RelayManager(timeout=10)
        for relay in self._relays:
            try:
                relay_manager.add_relay(relay)
            except Exception:
                pass

        filters = FiltersList(
            [
                Filters(
                    kinds=[EventKind.ENCRYPTED_DIRECT_MESSAGE],
                    pubkey_refs=[self._public_key.hex()],
                    since=since_ts,
                    limit=100,
                )
            ]
        )

        subscription_id = uuid.uuid4().hex
        relay_manager.add_subscription_on_all_relays(subscription_id, filters)

        try:
            relay_manager.run_sync()
            time.sleep(2)
        except Exception as e:
            self.log_error(f"Relay sync error: {e}")

        messages = []

        while relay_manager.message_pool.has_events():
            event_msg = relay_manager.message_pool.get_event()
            event = event_msg.event

            if event.pubkey == self._public_key.hex():
                continue

            try:
                enc_dm = EncryptedDirectMessage(
                    recipient_pubkey=self._public_key.hex(),
                    pubkey=event.pubkey,  # sender's pubkey
                    encrypted_message=event.content,
                )
                # Decrypt needs both our private key AND sender's public key
                enc_dm.decrypt(self._private_key.hex(), public_key_hex=event.pubkey)

                messages.append(
                    Message(
                        id=event.id or "",
                        sender=event.pubkey or "",
                        content=enc_dm.cleartext_content,
                        timestamp=event.created_at or 0,
                    )
                )
            except Exception as e:
                self.log_error(f"Failed to decrypt DM: {e}")

        relay_manager.close_all_relay_connections()
        return messages

    def send(self, recipient: str, message: str) -> str:
        """Send a DM to a recipient."""
        if not self._private_key:
            raise CommunicationError("Nostr not initialized")

        try:
            if recipient.startswith("npub"):
                recipient_pubkey = PublicKey.from_npub(recipient).hex()
            else:
                recipient_pubkey = recipient
        except Exception as e:
            raise CommunicationError(f"Invalid recipient: {e}")

        dm = EncryptedDirectMessage()
        dm.encrypt(
            self._private_key.hex(),
            recipient_pubkey=recipient_pubkey,
            cleartext_content=message,
        )

        dm_event = dm.to_event()
        dm_event.sign(self._private_key.hex())

        relay_manager = RelayManager(timeout=10)
        for relay in self._relays:
            try:
                relay_manager.add_relay(relay)
            except Exception:
                pass

        relay_manager.publish_event(dm_event)

        try:
            relay_manager.run_sync()
            time.sleep(2)
        except Exception as e:
            self.log_error(f"Publish error: {e}")

        relay_manager.close_all_relay_connections()
        return dm_event.id or ""


# Factory function for plugin discovery
def create_plugin() -> NostrPlugin:
    return NostrPlugin()
