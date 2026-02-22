"""Persistence plugin - saves conversation history per peer.

Priority: 15 (after security, before compaction)
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta


class PersistencePlugin(Plugin):
    """Conversation persistence plugin."""

    meta = PluginMeta(
        id="persistence",
        version="1.0.0",
        capabilities=["persistence"],
        dependencies=["config", "workspace"],
        priority=15,
        implements={
            "loop.on_message": "on_message_received",
            "loop.transform_history": "transform_history",
            "loop.after_send": "on_after_send",
        },
    )

    def __init__(self):
        self._memory_dir: Optional[Path] = None
        self._conversations: dict[str, dict] = {}
        self._current_peer: Optional[str] = None
        self._enabled: bool = False  # Default disabled, use --continue to enable
        self._registry = None

    def configure(self, config: dict) -> None:
        persistence_config = config.get("persistence", {})
        self._enabled = persistence_config.get("enabled", False)

    async def start(self) -> None:
        if not self._enabled:
            self.log_info("Disabled (use --continue to load history)")
            return

        # Get workspace path from workspace plugin
        if self._registry:
            workspace = self._registry.get("workspace")
            if workspace:
                self._memory_dir = workspace.get_path("memory") / "conversations"
            else:
                self._memory_dir = (
                    Path.home() / ".cobot" / "workspace" / "memory" / "conversations"
                )
        else:
            self._memory_dir = (
                Path.home() / ".cobot" / "workspace" / "memory" / "conversations"
            )

        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self.log_info(f"Memory dir: {self._memory_dir}")

    async def stop(self) -> None:
        pass

    def _npub_hash(self, npub: str) -> str:
        return hashlib.sha256(npub.encode()).hexdigest()[:16]

    def _get_path(self, npub: str) -> Path:
        return self._memory_dir / f"{self._npub_hash(npub)}.json"

    def _load(self, npub: str) -> dict:
        path = self._get_path(npub)
        if path.exists():
            try:
                return json.loads(path.read_text())
            except Exception:
                pass
        return {
            "peer_npub": npub,
            "messages": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _save(self, npub: str, data: dict) -> None:
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._get_path(npub).write_text(json.dumps(data, indent=2))

    def _get_conversation(self, npub: str) -> dict:
        if npub not in self._conversations:
            self._conversations[npub] = self._load(npub)
        return self._conversations[npub]

    def _add_message(self, npub: str, role: str, content: str) -> None:
        conv = self._get_conversation(npub)
        conv["messages"].append(
            {
                "role": role,
                "content": content,
                "timestamp": int(datetime.now(timezone.utc).timestamp()),
            }
        )
        self._save(npub, conv)

    # --- Hook Methods ---

    async def on_message_received(self, ctx: dict) -> dict:
        if not self._enabled:
            return ctx

        sender = ctx.get("sender", "")
        message = ctx.get("message", "")

        if sender and message:
            self._current_peer = sender
            self._add_message(sender, "user", message)

        return ctx

    async def transform_history(self, ctx: dict) -> dict:
        if not self._enabled:
            return ctx

        peer = ctx.get("peer", self._current_peer)
        messages = ctx.get("messages", [])

        if not peer or not messages:
            return ctx

        conv = self._get_conversation(peer)
        history = conv.get("messages", [])

        if not history:
            return ctx

        # Skip last user message (already in messages)
        history_to_inject = history[:-1] if history else []

        history_messages = [
            {"role": m["role"], "content": m["content"]} for m in history_to_inject
        ]

        if len(messages) >= 2:
            ctx["messages"] = [messages[0]] + history_messages + [messages[-1]]

        return ctx

    async def on_after_send(self, ctx: dict) -> dict:
        if not self._enabled:
            return ctx

        recipient = ctx.get("recipient", self._current_peer)
        text = ctx.get("text", "")

        if recipient and text:
            self._add_message(recipient, "assistant", text)

        return ctx


def create_plugin() -> PersistencePlugin:
    return PersistencePlugin()
