"""PPQ plugin - LLM inference via ppq.ai.

Priority: 20 (after config)
Capability: llm
"""

import os
from typing import Optional

import httpx

from ..base import Plugin, PluginMeta
from ..interfaces import LLMProvider, LLMResponse, LLMError


class InsufficientFundsError(LLMError):
    """Not enough credits for inference."""

    pass


class PPQPlugin(Plugin, LLMProvider):
    """PPQ.ai LLM provider plugin."""

    meta = PluginMeta(
        id="ppq",
        version="1.0.0",
        capabilities=["llm"],
        dependencies=["config"],
        priority=20,
        implements={
            "loop.before_llm": "on_before_llm_call",
            "loop.after_llm": "on_after_llm_call",
        },
    )

    def __init__(self):
        self._config: dict = {}
        self._api_base: str = "https://api.ppq.ai/v1"
        self._api_key: Optional[str] = None
        self._model: str = "gpt-5-nano"

    def configure(self, config: dict) -> None:
        """Receive ppq-specific configuration."""
        self._config = config
        ppq_config = config.get("ppq", {})
        self._api_base = ppq_config.get("api_base", "https://api.ppq.ai/v1").rstrip("/")
        self._api_key = ppq_config.get("api_key") or os.environ.get("PPQ_API_KEY")
        self._model = ppq_config.get("model", "gpt-5-nano")

    async def start(self) -> None:
        """Validate configuration."""
        if not self._api_key:
            self.log_warn("No API key configured")
        else:
            self.log_info(f"Initialized with model {self._model}")

    async def stop(self) -> None:
        """Nothing to clean up."""
        pass

    # --- LLMProvider Interface ---

    def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        model: Optional[str] = None,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Chat completion via ppq.ai API."""
        if not self._api_key:
            raise LLMError("PPQ API key not configured")

        model = model or self._model

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }

        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = httpx.post(
                f"{self._api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )

            if response.status_code == 402:
                raise InsufficientFundsError("Not enough credits for inference")

            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError as e:
            raise LLMError(f"API error: {e.response.status_code} - {e.response.text}")
        except httpx.RequestError as e:
            raise LLMError(f"Request failed: {e}")

        # Parse response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})

        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            model=data.get("model", model),
            usage=data.get("usage"),
        )

    # --- Hook Methods ---

    async def on_before_llm_call(self, ctx: dict) -> dict:
        """Log before LLM call."""
        return ctx

    async def on_after_llm_call(self, ctx: dict) -> dict:
        """Log after LLM call."""
        return ctx


# Factory function for plugin discovery
def create_plugin() -> PPQPlugin:
    return PPQPlugin()
