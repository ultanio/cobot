"""Ollama embedding client for knowledge plugin.

Provides local embeddings via Ollama with nomic-embed-text model.
This module is optional - knowledge plugin works without embeddings.
"""

import json
import sys
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError


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
                    print(
                        f"[Knowledge] Ollama running but model '{self.model}' not found. "
                        f"Available: {models}. Run: ollama pull {self.model}",
                        file=sys.stderr,
                    )
                return self._available
        except URLError as e:
            print(f"[Knowledge] Ollama not available: {e}", file=sys.stderr)
            self._available = False
            return False
        except Exception as e:
            print(f"[Knowledge] Ollama check error: {e}", file=sys.stderr)
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
            print(f"[Knowledge] Embedding error: {e}", file=sys.stderr)
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
