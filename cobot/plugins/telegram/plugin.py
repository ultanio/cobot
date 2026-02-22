"""Telegram plugin - multi-group message logging and archival.

Implements session.* extension points for cobot channel integration,
plus telegram-specific extension points for archival/logging.

Priority: 30 (after session)
Capability: communication

Session Extension Points (implemented):
  - session.receive: Poll for new messages
  - session.send: Send a message
  - session.typing: Show typing indicator

Telegram Extension Points (defined):
  - telegram.on_message: Called when a new message is received
  - telegram.on_edit: Called when a message is edited
  - telegram.on_delete: Called when a message is deleted
  - telegram.on_media: Called when media is downloaded (with local path)
"""

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from telegram import Bot, Update
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..base import Plugin, PluginMeta
from ..session import IncomingMessage, OutgoingMessage


# --- Legacy types for backward compatibility ---


@dataclass
class Message:
    """Standard message format (legacy)."""

    id: str
    sender: str
    content: str
    timestamp: int


class CommunicationError(Exception):
    """Communication error."""

    pass


# --- Telegram-specific types ---


@dataclass
class GroupConfig:
    """Configuration for a single group."""

    id: int
    name: str = ""
    enabled: bool = True


@dataclass
class TelegramMessage:
    """Extended message with Telegram-specific fields."""

    group_id: int
    group_name: str
    message_id: int
    from_user: dict
    timestamp: str
    text: str
    reply_to: Optional[int] = None
    edit_date: Optional[str] = None
    media: Optional[dict] = None
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary for extension points."""
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "message_id": self.message_id,
            "from_user": self.from_user,
            "timestamp": self.timestamp,
            "text": self.text,
            "reply_to": self.reply_to,
            "edit_date": self.edit_date,
            "media": self.media,
            "raw": self.raw,
        }

    def to_incoming_message(self) -> IncomingMessage:
        """Convert to session IncomingMessage."""
        return IncomingMessage(
            id=str(self.message_id),
            channel_type="telegram",
            channel_id=str(self.group_id),
            sender_id=str(self.from_user.get("id", "")),
            sender_name=self.from_user.get("first_name", "")
            or self.from_user.get("username", "Unknown"),
            content=self.text,
            timestamp=datetime.fromisoformat(self.timestamp),
            reply_to=str(self.reply_to) if self.reply_to else None,
            media=[self.media] if self.media else [],
            metadata={"raw": self.raw, "group_name": self.group_name},
        )


# --- Telegram Plugin ---


class TelegramPlugin(Plugin):
    """Telegram multi-group logging plugin.

    Implements session.* extension points for cobot integration and
    defines telegram.* extension points for archival/logging.
    """

    meta = PluginMeta(
        id="telegram",
        version="0.2.0",
        capabilities=["communication"],
        dependencies=["session"],
        priority=30,  # After session (10)
        extension_points=[
            "telegram.on_message",
            "telegram.on_edit",
            "telegram.on_delete",
            "telegram.on_media",
        ],
        implements={
            "loop.before_llm": "on_before_llm_call",
            "session.receive": "poll_updates",
            "session.send": "send_message",
            "session.typing": "send_typing",
        },
    )

    def __init__(self):
        self._bot_token: Optional[str] = None
        self._groups: dict[int, GroupConfig] = {}
        self._media_dir: Path = Path("./media")
        self._app: Optional[Application] = None
        self._bot: Optional[Bot] = None
        self._running = False
        self._message_queue: list[TelegramMessage] = []  # For session.receive
        self._message_buffer: list[TelegramMessage] = []  # For legacy receive()
        self._last_update_id: int = 0
        self._default_group_id: Optional[int] = None
        self._poll_timeout: int = 30  # Long polling timeout (seconds)
        self._extension_handlers: dict[str, list] = {
            "telegram.on_message": [],
            "telegram.on_edit": [],
            "telegram.on_delete": [],
            "telegram.on_media": [],
        }

    def configure(self, config: dict) -> None:
        """Configure the Telegram plugin.

        Config format:
            telegram:
              bot_token: "${TELEGRAM_BOT_TOKEN}"
              groups:
                - id: -100123456789
                  name: "dev-chat"
                - id: -100987654321
                  name: "announcements"
              media_dir: "./media"
              default_group: -100123456789  # Optional: for broadcasts
              poll_timeout: 30  # Long polling timeout in seconds (default: 30)
        """
        # Extract telegram section from full config (or use config directly for tests)
        tg_config = config.get("telegram", config) if "telegram" in config else config

        self._bot_token = tg_config.get("bot_token") or os.environ.get(
            "TELEGRAM_BOT_TOKEN"
        )

        if not self._bot_token:
            self.log_warn("No bot_token configured")
            return

        # Parse groups
        groups_config = tg_config.get("groups", [])
        for g in groups_config:
            if isinstance(g, dict) and "id" in g:
                group_id = int(g["id"])
                self._groups[group_id] = GroupConfig(
                    id=group_id,
                    name=g.get("name", str(group_id)),
                    enabled=g.get("enabled", True),
                )

        # Default group for broadcasts
        self._default_group_id = tg_config.get("default_group")
        if not self._default_group_id and self._groups:
            self._default_group_id = next(iter(self._groups.keys()))

        # Media directory
        media_dir = tg_config.get("media_dir", "./media")
        self._media_dir = Path(media_dir)
        self._media_dir.mkdir(parents=True, exist_ok=True)

        # Long polling timeout (default: 30 seconds)
        self._poll_timeout = tg_config.get("poll_timeout", 30)

        self.log_info(f"Configured with {len(self._groups)} groups")

    def set_registry(self, registry) -> None:
        """Set registry reference for calling extension points."""
        self._registry = registry

    def register_handler(self, extension_point: str, handler) -> None:
        """Register a handler for an extension point.

        Args:
            extension_point: One of telegram.on_message, on_edit, on_delete, on_media
            handler: Callable that takes a context dict
        """
        if extension_point in self._extension_handlers:
            self._extension_handlers[extension_point].append(handler)

    async def start(self) -> None:
        """Start the Telegram bot."""
        if not self._bot_token:
            self.log_error("Cannot start: no bot token")
            return

        self._bot = Bot(token=self._bot_token)
        self._app = Application.builder().token(self._bot_token).build()

        # Register handlers for push mode
        self._app.add_handler(
            MessageHandler(filters.ALL & ~filters.COMMAND, self._handle_message)
        )

        self._running = True
        self.log_info("Bot initialized")

    async def stop(self) -> None:
        """Stop the Telegram bot."""
        self._running = False
        if self._app:
            # Graceful shutdown
            pass
        self.log_info("Bot stopped")

    # --- Hook: on_before_llm_call ---

    async def on_before_llm_call(self, ctx: dict) -> dict:
        """Send typing indicator before LLM call.

        This shows the user that the bot is "thinking" while
        waiting for the LLM response.
        """
        channel_type = ctx.get("channel_type", "")
        channel_id = ctx.get("channel_id", "")

        if channel_type == "telegram" and channel_id:
            self.send_typing(channel_id)

        return ctx

    # --- session.receive implementation ---

    def poll_updates(self) -> list[IncomingMessage]:
        """Poll Telegram for new messages (session.receive).

        Uses long polling - Telegram holds the connection open and returns
        immediately when new messages arrive, making the bot feel instant.

        Returns:
            List of IncomingMessage objects
        """
        if not self._bot:
            return []

        messages = []

        try:
            # Long polling using httpx
            import httpx

            url = f"https://api.telegram.org/bot{self._bot_token}/getUpdates"
            poll_timeout = self._poll_timeout
            params = {
                "offset": self._last_update_id + 1,
                "timeout": poll_timeout,
                "limit": 100,
            }

            # HTTP timeout must be longer than Telegram's long poll timeout
            with httpx.Client(timeout=poll_timeout + 5.0) as client:
                resp = client.get(url, params=params)
                data = resp.json()

            if not data.get("ok"):
                return messages

            for update in data.get("result", []):
                self._last_update_id = update["update_id"]

                # Handle message or edited_message
                msg = update.get("message") or update.get("edited_message")
                if not msg:
                    continue

                is_edit = "edited_message" in update
                chat_id = msg["chat"]["id"]

                # Security: Only process messages from configured groups
                if chat_id not in self._groups:
                    chat_name = msg["chat"].get("title", str(chat_id))
                    self.log_warn(
                        f"Ignoring message from unconfigured group {chat_id} ({chat_name}): "
                        f"add group to config to enable processing"
                    )
                    continue

                group = self._groups[chat_id]
                if not group.enabled:
                    continue

                # Build user info
                from_user = {}
                if "from" in msg:
                    from_user = {
                        "id": msg["from"]["id"],
                        "username": msg["from"].get("username", ""),
                        "first_name": msg["from"].get("first_name", ""),
                        "last_name": msg["from"].get("last_name", ""),
                    }

                # Build TelegramMessage
                telegram_msg = TelegramMessage(
                    group_id=chat_id,
                    group_name=group.name,
                    message_id=msg["message_id"],
                    from_user=from_user,
                    timestamp=datetime.fromtimestamp(msg["date"]).isoformat(),
                    text=msg.get("text", "") or msg.get("caption", ""),
                    reply_to=msg.get("reply_to_message", {}).get("message_id"),
                    edit_date=datetime.fromtimestamp(msg["edit_date"]).isoformat()
                    if msg.get("edit_date")
                    else None,
                    raw=msg,
                )

                # Add to message buffer for legacy API
                self._message_buffer.append(telegram_msg)

                # Call telegram extension points
                ctx = {"message": telegram_msg.to_dict()}
                if is_edit:
                    self._call_extension("telegram.on_edit", ctx)
                else:
                    self._call_extension("telegram.on_message", ctx)

                # Convert to IncomingMessage for session
                messages.append(telegram_msg.to_incoming_message())

        except Exception as e:
            self.log_error(f"Poll error: {e}")

        return messages

    # --- session.send implementation ---

    def send_message(self, message: OutgoingMessage) -> bool:
        """Send a message to Telegram (session.send).

        Args:
            message: OutgoingMessage with channel_id set to group ID

        Returns:
            True if sent successfully
        """
        if not self._bot_token:
            return False

        try:
            import httpx

            url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
            payload = {
                "chat_id": int(message.channel_id),
                "text": message.content,
            }

            # Reply to specific message
            if message.reply_to:
                payload["reply_to_message_id"] = int(message.reply_to)

            # Parse mode from metadata
            if message.metadata.get("parse_mode"):
                payload["parse_mode"] = message.metadata["parse_mode"]

            with httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                data = resp.json()

            return data.get("ok", False)

        except Exception as e:
            self.log_error(f"Send error: {e}")
            return False

    # --- session.typing implementation ---

    def send_typing(self, channel_id: str) -> None:
        """Send typing indicator (session.typing).

        Args:
            channel_id: Group/chat ID
        """
        if not self._bot_token:
            return

        try:
            import httpx

            url = f"https://api.telegram.org/bot{self._bot_token}/sendChatAction"
            payload = {
                "chat_id": int(channel_id),
                "action": "typing",
            }

            with httpx.Client(timeout=5.0) as client:
                client.post(url, json=payload)

        except Exception as e:
            self.log_error(f"Typing error: {e}")

    # --- Helper for session.broadcast ---

    def get_default_channel_id(self) -> Optional[str]:
        """Get default channel for broadcasts."""
        if self._default_group_id:
            return str(self._default_group_id)
        return None

    # --- Push mode handler (for run_polling) ---

    async def _handle_message(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle incoming message in push mode."""
        if not update.message and not update.edited_message:
            return

        msg = update.edited_message or update.message
        is_edit = update.edited_message is not None

        chat_id = msg.chat_id
        if chat_id not in self._groups:
            self._groups[chat_id] = GroupConfig(id=chat_id, name=str(chat_id))

        group = self._groups[chat_id]
        if not group.enabled:
            return

        from_user = {}
        if msg.from_user:
            from_user = {
                "id": msg.from_user.id,
                "username": msg.from_user.username or "",
                "first_name": msg.from_user.first_name or "",
                "last_name": msg.from_user.last_name or "",
            }

        telegram_msg = TelegramMessage(
            group_id=chat_id,
            group_name=group.name,
            message_id=msg.message_id,
            from_user=from_user,
            timestamp=msg.date.isoformat()
            if msg.date
            else datetime.utcnow().isoformat(),
            text=msg.text or msg.caption or "",
            reply_to=msg.reply_to_message.message_id if msg.reply_to_message else None,
            edit_date=msg.edit_date.isoformat() if msg.edit_date else None,
            raw=msg.to_dict() if hasattr(msg, "to_dict") else {},
        )

        # Handle media
        media_info = await self._process_media(msg, context)
        if media_info:
            telegram_msg.media = media_info

        # Add to queues
        self._message_queue.append(telegram_msg)
        self._message_buffer.append(telegram_msg)

        # Call extension points
        ctx = {"message": telegram_msg.to_dict()}

        if is_edit:
            self._call_extension("telegram.on_edit", ctx)
        else:
            self._call_extension("telegram.on_message", ctx)

        if media_info:
            self._call_extension("telegram.on_media", ctx)

    async def _process_media(
        self, msg, context: ContextTypes.DEFAULT_TYPE
    ) -> Optional[dict]:
        """Download and process media attachments."""
        media_info = None
        file_obj = None
        media_type = None

        if msg.photo:
            media_type = "photo"
            file_obj = msg.photo[-1]
        elif msg.document:
            media_type = "document"
            file_obj = msg.document
        elif msg.video:
            media_type = "video"
            file_obj = msg.video
        elif msg.voice:
            media_type = "voice"
            file_obj = msg.voice
        elif msg.audio:
            media_type = "audio"
            file_obj = msg.audio
        elif msg.sticker:
            media_type = "sticker"
            file_obj = msg.sticker

        if file_obj and hasattr(file_obj, "file_id"):
            try:
                date_str = datetime.utcnow().strftime("%Y-%m-%d")
                day_dir = self._media_dir / date_str
                day_dir.mkdir(parents=True, exist_ok=True)

                file = await context.bot.get_file(file_obj.file_id)

                ext = ""
                if hasattr(file_obj, "file_name") and file_obj.file_name:
                    ext = Path(file_obj.file_name).suffix
                elif media_type == "photo":
                    ext = ".jpg"
                elif media_type == "voice":
                    ext = ".ogg"
                elif media_type == "video":
                    ext = ".mp4"
                elif media_type == "sticker":
                    ext = ".webp"

                filename = f"{media_type}_{msg.message_id}{ext}"
                local_path = day_dir / filename

                await file.download_to_drive(str(local_path))

                media_info = {
                    "type": media_type,
                    "file_id": file_obj.file_id,
                    "local_path": str(local_path),
                    "file_size": getattr(file_obj, "file_size", None),
                    "mime_type": getattr(file_obj, "mime_type", None),
                }

                self.log_info(f"Downloaded {media_type}: {local_path}")

            except Exception as e:
                self.log_error(f"Media download failed: {e}")

        return media_info

    def _call_extension(self, point: str, ctx: dict) -> dict:
        """Call extension point handlers."""
        for handler in self._extension_handlers.get(point, []):
            try:
                handler(ctx)
            except Exception as e:
                self.log_error(f"Handler error for {point}: {e}")

        if self._registry:
            return self._registry.call_extension(point, ctx)
        return ctx

    # --- Legacy CommunicationProvider Interface ---

    def get_identity(self) -> dict:
        """Get bot identity."""
        if self._bot:
            return {
                "type": "telegram_bot",
                "token_prefix": self._bot_token[:10] + "..." if self._bot_token else "",
                "groups": list(self._groups.keys()),
            }
        return {"type": "telegram_bot", "status": "not_configured"}

    def receive(self, since_minutes: int = 5) -> list[Message]:
        """Get buffered messages (legacy API)."""
        cutoff = time.time() - (since_minutes * 60)
        messages = []

        for tm in self._message_buffer:
            try:
                msg_time = datetime.fromisoformat(tm.timestamp).timestamp()
                if msg_time >= cutoff:
                    messages.append(
                        Message(
                            id=str(tm.message_id),
                            sender=tm.from_user.get(
                                "username", str(tm.from_user.get("id", "unknown"))
                            ),
                            content=tm.text,
                            timestamp=int(msg_time),
                        )
                    )
            except Exception:
                pass

        self._message_buffer = [
            m
            for m in self._message_buffer
            if datetime.fromisoformat(m.timestamp).timestamp() >= cutoff
        ]

        return messages

    def send(self, recipient: str, message: str) -> str:
        """Send a message (legacy API)."""
        result = self.send_message(
            OutgoingMessage(
                channel_type="telegram",
                channel_id=recipient,
                content=message,
            )
        )
        return "sent" if result else "failed"

    def run_polling(self) -> None:
        """Start polling for messages (blocking, push mode)."""
        if not self._app:
            self.log_error("Cannot poll: app not initialized")
            return

        self.log_info("Starting polling...")
        self._app.run_polling(allowed_updates=Update.ALL_TYPES)

    async def run_polling_async(self) -> None:
        """Start polling for messages (async, push mode)."""
        if not self._app:
            self.log_error("Cannot poll: app not initialized")
            return

        self.log_info("Starting async polling...")
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(allowed_updates=Update.ALL_TYPES)

    # --- Setup Wizard Extension ---

    def wizard_section(self) -> dict | None:
        """Return wizard section info for telegram."""
        return {
            "key": "telegram",
            "name": "Telegram",
            "description": "Connect to Telegram for messaging",
        }

    def wizard_configure(self, config: dict) -> dict:
        """Interactive telegram configuration for the setup wizard."""
        import click

        agent_name = config.get("identity", {}).get("name", "Cobot")
        click.echo(f"\nSetting up Telegram for {agent_name}")
        click.echo("You'll need a bot token from @BotFather on Telegram.\n")

        # Bot token
        token = click.prompt(
            "Bot token (or env var)",
            default="${TELEGRAM_BOT_TOKEN}",
        )

        # Groups (optional)
        groups = []
        click.echo("\nGroups are auto-detected when messages arrive.")
        if click.confirm("Add a group manually?", default=False):
            while True:
                group_id = click.prompt("Group ID (e.g., -100123456789)", type=int)
                group_name = click.prompt("Group name", default=str(group_id))
                groups.append({"id": group_id, "name": group_name})
                if not click.confirm("Add another group?", default=False):
                    break

        # Poll timeout
        poll_timeout = click.prompt(
            "Long poll timeout (seconds)",
            default=30,
            type=int,
        )

        result = {
            "bot_token": token,
            "poll_timeout": poll_timeout,
        }
        if groups:
            result["groups"] = groups

        # Add to external plugins list
        click.echo("\nNote: Add 'cobot_telegram' to plugins.external in config.")

        return result


def create_plugin() -> TelegramPlugin:
    """Factory function to create the plugin."""
    return TelegramPlugin()
