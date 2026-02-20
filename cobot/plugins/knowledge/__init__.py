"""Knowledge plugin - local vector search and long-term memory.

Provides semantic search over a local knowledge base using SQLite + FTS5,
with optional vector embeddings via Ollama.
"""

from .plugin import KnowledgePlugin, create_plugin

__all__ = ["KnowledgePlugin", "create_plugin"]
