"""Ollama embedding client for knowledge plugin.

Provides local embeddings via Ollama with nomic-embed-text model.
This module is optional - knowledge plugin works without embeddings.
"""

import json
import os
import sys
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


_LOG_SOURCE_WIDTH = 12


def _log(level: str, msg: str) -> None:
    """Log with consistent format."""
    level_char = level[0].upper()
    use_color = (
        not os.environ.get("NO_COLOR")
        and hasattr(sys.stderr, "isatty")
        and sys.stderr.isatty()
    )
    if use_color:
        colors = {"I": "\033[32m", "W": "\033[33m", "E": "\033[31m"}
        reset = "\033[0m"
        color = colors.get(level_char, "")
        level_str = f"{color}[{level_char}]{reset}" if color else f"[{level_char}]"
    else:
        level_str = f"[{level_char}]"
    source = "knowledge".ljust(_LOG_SOURCE_WIDTH)
    print(f"{level_str} [{source}] {msg}", file=sys.stderr)


class OllamaEmbeddings:
    """Client for Ollama embeddings API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "nomic-embed-text",
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """Check if Ollama is running and model is available."""
        if self._available is not None:
            return self._available

        try:
            req = Request(f"{self.base_url}/api/tags")
            with urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                models = [
                    m.get("name", "").split(":")[0] for m in data.get("models", [])
                ]
                self._available = self.model in models
                if not self._available:
                    _log(
                        "warn",
                        f"Ollama running but model '{self.model}' not found. "
                        f"Available: {models}. Run: ollama pull {self.model}",
                    )
                return self._available
        except URLError as e:
            _log("warn", f"Ollama not available: {e}")
            self._available = False
            return False
        except Exception as e:
            _log("error", f"Ollama check error: {e}")
            self._available = False
            return False

    def embed(self, text: str) -> Optional[list[float]]:
        """Generate embedding for a single text."""
        if not self.is_available():
            return None

        try:
            payload = json.dumps({"model": self.model, "prompt": text}).encode()
            req = Request(
                f"{self.base_url}/api/embeddings",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read())
                return data.get("embedding")
        except Exception as e:
            _log("error", f"Embedding error: {e}")
            return None

    def embed_batch(
        self, texts: list[str], on_progress: Optional[callable] = None
    ) -> list[Optional[list[float]]]:
        """Generate embeddings for multiple texts.

        Args:
            texts: List of texts to embed
            on_progress: Optional callback(index, total) for progress

        Returns:
            List of embeddings (None for failed items)
        """
        results = []
        for i, text in enumerate(texts):
            embedding = self.embed(text)
            results.append(embedding)
            if on_progress:
                on_progress(i + 1, len(texts))
        return results
