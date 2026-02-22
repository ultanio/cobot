"""Compaction plugin - summarizes old conversation history.

Priority: 16 (after persistence)
"""

import asyncio

from ..base import Plugin, PluginMeta


# Token budget defaults
DEFAULT_MAX_TOKENS = 12000
DEFAULT_TARGET_RECENT_TOKENS = 4000
DEFAULT_CHARS_PER_TOKEN = 4


class CompactionPlugin(Plugin):
    """Context compaction plugin."""

    meta = PluginMeta(
        id="compaction",
        version="1.0.0",
        capabilities=["compaction"],
        dependencies=["config", "persistence"],
        consumes=["llm"],
        priority=16,
        implements={
            "loop.transform_history": "transform_history",
        },
    )

    def __init__(self):
        self._max_tokens = DEFAULT_MAX_TOKENS
        self._target_recent_tokens = DEFAULT_TARGET_RECENT_TOKENS
        self._chars_per_token = DEFAULT_CHARS_PER_TOKEN

    def configure(self, config: dict) -> None:
        compaction_cfg = config.get("compaction", {})
        self._max_tokens = compaction_cfg.get("max_tokens", DEFAULT_MAX_TOKENS)
        self._target_recent_tokens = compaction_cfg.get(
            "target_recent_tokens", DEFAULT_TARGET_RECENT_TOKENS
        )
        self._chars_per_token = compaction_cfg.get(
            "chars_per_token", DEFAULT_CHARS_PER_TOKEN
        )

    async def start(self) -> None:
        self.log_info("Ready")

    async def stop(self) -> None:
        pass

    def _estimate_tokens(self, messages: list[dict]) -> int:
        total = sum(len(m.get("content", "")) for m in messages)
        return total // self._chars_per_token

    def _get_llm(self):
        """Get LLM from registry."""
        if self._registry:
            return self._registry.get_by_capability("llm")
        return None

    async def _summarize(self, messages: list[dict]) -> str:
        """Summarize messages using LLM."""
        if not messages:
            return ""

        formatted = []
        for m in messages:
            role = m.get("role", "")
            content = m.get("content", "")[:500]
            formatted.append(f"{role}: {content}")

        text = "\n".join(formatted)

        llm = self._get_llm()
        if not llm:
            return f"[Earlier conversation - {len(messages)} messages]"

        try:
            # Use asyncio.to_thread if chat() is synchronous,
            # or await directly if it's async
            chat_fn = llm.chat
            response = chat_fn(
                messages=[
                    {
                        "role": "system",
                        "content": "Summarize this conversation in 2-3 sentences. Focus on key topics and decisions.",
                    },
                    {"role": "user", "content": f"Conversation:\n\n{text}"},
                ],
                max_tokens=200,
            )
            # Handle both sync and async return values
            if asyncio.iscoroutine(response):
                response = await response
            return response.content
        except Exception as e:
            self.log_error(f"Summarization failed: {e}")
            return f"[Earlier conversation - {len(messages)} messages]"

    async def transform_history(self, ctx: dict) -> dict:
        """Compact history if too long."""
        messages = ctx.get("messages", [])

        if len(messages) < 3:
            return ctx

        system_msg = messages[0] if messages[0].get("role") == "system" else None
        current_msg = messages[-1] if messages[-1].get("role") == "user" else None

        if system_msg and current_msg:
            history = messages[1:-1]
        elif system_msg:
            history = messages[1:]
            current_msg = None
        else:
            history = messages[:-1] if current_msg else messages
            system_msg = None

        if not history:
            return ctx

        total_tokens = self._estimate_tokens(history)

        if total_tokens <= self._max_tokens:
            return ctx

        self.log_info(f"{total_tokens} tokens, compacting...")

        # Find split point
        recent_tokens = 0
        split_index = len(history)

        for i in range(len(history) - 1, -1, -1):
            msg_tokens = len(history[i].get("content", "")) // self._chars_per_token
            if recent_tokens + msg_tokens > self._target_recent_tokens:
                split_index = i + 1
                break
            recent_tokens += msg_tokens

        if split_index <= 0:
            return ctx

        old_messages = history[:split_index]
        recent_messages = history[split_index:]

        summary = await self._summarize(old_messages)

        new_messages = []
        if system_msg:
            new_messages.append(system_msg)

        new_messages.append(
            {"role": "system", "content": f"[Earlier conversation summary: {summary}]"}
        )

        new_messages.extend(recent_messages)

        if current_msg:
            new_messages.append(current_msg)

        ctx["messages"] = new_messages
        return ctx


def create_plugin() -> CompactionPlugin:
    return CompactionPlugin()
