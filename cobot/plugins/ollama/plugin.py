"""Ollama plugin - local LLM inference via Ollama.

Priority: 20 (after config)
Capability: llm
"""

import os
from typing import Optional

import httpx

from ..base import Plugin, PluginMeta
from ..interfaces import LLMProvider, LLMResponse, LLMError


class OllamaPlugin(Plugin, LLMProvider):
    """Ollama local LLM provider plugin."""

    meta = PluginMeta(
        id="ollama",
        version="1.0.0",
        capabilities=["llm"],
        dependencies=["config"],
        priority=20,
    )

    def __init__(self):
        self._config: dict = {}
        self._host: str = "http://localhost:11434"
        self._model: str = "llama3.2:latest"

    def configure(self, config: dict) -> None:
        """Receive ollama-specific configuration."""
        self._config = config
        ollama_config = config.get("ollama", {})
        self._host = ollama_config.get("host") or os.environ.get(
            "OLLAMA_HOST", "http://localhost:11434"
        )
        self._host = self._host.rstrip("/")
        self._model = ollama_config.get("model", "llama3.2:latest")

    async def start(self) -> None:
        """Test connection to Ollama."""
        try:
            models = self.list_models()
            self.log_info(f"Connected to {self._host}, {len(models)} models available")
            self.log_info(f"Using model: {self._model}")
        except LLMError as e:
            self.log_warn(f"{e}")

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
        """Chat completion via Ollama API."""
        model = model or self._model

        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
            },
        }

        if tools:
            payload["tools"] = tools

        headers = {"Content-Type": "application/json"}

        try:
            response = httpx.post(
                f"{self._host}/api/chat",
                headers=headers,
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            data = response.json()

        except httpx.HTTPStatusError as e:
            raise LLMError(
                f"Ollama API error: {e.response.status_code} - {e.response.text}"
            )
        except httpx.ConnectError:
            raise LLMError(
                f"Cannot connect to Ollama at {self._host}. Is Ollama running?"
            )
        except httpx.RequestError as e:
            raise LLMError(f"Request failed: {e}")

        # Parse Ollama response
        message = data.get("message", {})

        # Convert tool calls to OpenAI format
        tool_calls = None
        if message.get("tool_calls"):
            tool_calls = []
            for i, tc in enumerate(message["tool_calls"]):
                tool_calls.append(
                    {
                        "id": f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", "{}"),
                        },
                    }
                )

        # Build usage dict
        usage = None
        if data.get("prompt_eval_count") or data.get("eval_count"):
            usage = {
                "prompt_tokens": data.get("prompt_eval_count", 0),
                "completion_tokens": data.get("eval_count", 0),
                "total_tokens": data.get("prompt_eval_count", 0)
                + data.get("eval_count", 0),
            }

        return LLMResponse(
            content=message.get("content", ""),
            tool_calls=tool_calls,
            model=data.get("model", model),
            usage=usage,
        )

    # --- Ollama-specific methods ---

    def list_models(self) -> list[str]:
        """List available models on the Ollama server."""
        try:
            response = httpx.get(
                f"{self._host}/api/tags",
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            return [m.get("name", "") for m in data.get("models", [])]
        except Exception as e:
            raise LLMError(f"Failed to list models: {e}")

    def generate(self, prompt: str, model: Optional[str] = None) -> str:
        """One-shot text generation (non-chat)."""
        model = model or self._model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }

        try:
            response = httpx.post(
                f"{self._host}/api/generate",
                json=payload,
                timeout=120.0,
            )
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            raise LLMError(f"Generate failed: {e}")

    def embeddings(self, text: str, model: str = "nomic-embed-text") -> list[float]:
        """Get embeddings for text."""
        payload = {"model": model, "input": text}

        try:
            response = httpx.post(
                f"{self._host}/api/embeddings",
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            return response.json().get("embeddings", [[]])[0]
        except Exception as e:
            raise LLMError(f"Embeddings failed: {e}")


# Factory function for plugin discovery
def create_plugin() -> OllamaPlugin:
    return OllamaPlugin()
