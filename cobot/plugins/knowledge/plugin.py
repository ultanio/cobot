"""Knowledge plugin - local vector search and long-term memory.

Provides semantic search over a local knowledge base using SQLite + FTS5,
with optional vector embeddings via Ollama.

Priority: 22 (after config, before tools)
Capabilities: knowledge, tools
"""

from pathlib import Path
from typing import Optional

from ..base import Plugin, PluginMeta
from ..interfaces import ToolProvider
from .db import KnowledgeDB
from .embeddings import OllamaEmbeddings
from .search import KnowledgeSearch


# Tool definitions in OpenAI format
KNOWLEDGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": "Search the knowledge base for relevant information. Supports keyword search, semantic/vector search, or hybrid mode.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query - keywords or natural language question",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["fts", "semantic", "hybrid"],
                        "default": "hybrid",
                        "description": "Search mode: 'fts' for keyword, 'semantic' for vector similarity, 'hybrid' for combined",
                    },
                    "limit": {
                        "type": "integer",
                        "default": 5,
                        "description": "Maximum number of results to return",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_add",
            "description": "Add a new entry to the knowledge base. Use this to remember facts, references, or important information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The content to store - the main text or information",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title or summary",
                    },
                    "url": {
                        "type": "string",
                        "description": "Optional source URL",
                    },
                    "source": {
                        "type": "string",
                        "default": "agent",
                        "description": "Source identifier (e.g., 'agent', 'conversation', 'bookmark')",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_stats",
            "description": "Get statistics about the knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


class KnowledgePlugin(Plugin, ToolProvider):
    """Knowledge base plugin with search capabilities."""

    meta = PluginMeta(
        id="knowledge",
        version="1.0.0",
        capabilities=["knowledge", "tools"],
        dependencies=["config"],
        priority=22,  # After config, before tools
        extension_points=[
            "knowledge.before_ingest",  # Plugins can enrich/filter incoming entries
            "knowledge.after_search",  # Plugins can re-rank/filter search results
        ],
    )

    def __init__(self):
        self._config: dict = {}
        self._db: Optional[KnowledgeDB] = None
        self._embeddings: Optional[OllamaEmbeddings] = None
        self._search: Optional[KnowledgeSearch] = None
        self._embedding_enabled: bool = True
        self._restart_requested: bool = False

    def configure(self, config: dict) -> None:
        """Configure knowledge plugin settings."""
        knowledge_config = config.get("knowledge", {})

        # Database path
        db_path = knowledge_config.get("db_path", "~/.cobot/knowledge.db")
        self._db_path = Path(db_path).expanduser()

        # Embedding settings
        self._embedding_enabled = knowledge_config.get("embedding_enabled", True)
        self._ollama_url = knowledge_config.get("ollama_url", "http://localhost:11434")
        self._embedding_model = knowledge_config.get(
            "embedding_model", "nomic-embed-text"
        )

        self._config = knowledge_config

    async def start(self) -> None:
        """Initialize database and search."""
        # Initialize database
        self._db = KnowledgeDB(self._db_path)
        self._db.open()

        # Initialize embeddings if enabled
        if self._embedding_enabled:
            self._embeddings = OllamaEmbeddings(
                base_url=self._ollama_url,
                model=self._embedding_model,
            )
            if self._embeddings.is_available():
                self.log_info(f"Embeddings enabled: {self._embedding_model}")
            else:
                self.log_info("Embeddings disabled: Ollama not available")
                self._embeddings = None

        # Initialize search
        self._search = KnowledgeSearch(self._db, self._embeddings)

        self.log_info(f"Database: {self._db_path} ({self._db.count()} entries)")

    async def stop(self) -> None:
        """Clean up resources."""
        if self._db:
            self._db.close()
            self._db = None

    # --- ToolProvider Interface ---

    def get_definitions(self) -> list[dict]:
        """Get tool definitions for LLM."""
        return KNOWLEDGE_TOOLS

    def execute(self, tool_name: str, args: dict) -> str:
        """Execute a knowledge tool."""
        if tool_name == "knowledge_search":
            return self._tool_search(args)
        elif tool_name == "knowledge_add":
            return self._tool_add(args)
        elif tool_name == "knowledge_stats":
            return self._tool_stats()
        else:
            return f"Unknown tool: {tool_name}"

    @property
    def restart_requested(self) -> bool:
        """Check if restart was requested."""
        return self._restart_requested

    # --- Tool Implementations ---

    def _tool_search(self, args: dict) -> str:
        """Execute knowledge_search tool."""
        if not self._search:
            return "Knowledge base not initialized"

        query = args.get("query", "")
        mode = args.get("mode", "hybrid")
        limit = args.get("limit", 5)

        # Map "semantic" to "vector" for internal use
        if mode == "semantic":
            mode = "vector"

        results = self._search.search(query, mode=mode, limit=limit)

        if not results:
            return f"No results found for: {query}"

        # Format results
        output = [f"Found {len(results)} result(s) for '{query}':\n"]
        for i, result in enumerate(results, 1):
            entry = result.entry
            title = entry.title or "(untitled)"
            content = (
                entry.content[:200] + "..."
                if len(entry.content) > 200
                else entry.content
            )
            tags = ", ".join(entry.tags) if entry.tags else ""

            output.append(f"{i}. [{entry.source}] {title}")
            if entry.url:
                output.append(f"   URL: {entry.url}")
            if tags:
                output.append(f"   Tags: {tags}")
            output.append(f"   {content}")
            output.append(f"   (score: {result.score:.2f}, type: {result.match_type})")
            output.append("")

        return "\n".join(output)

    def _tool_add(self, args: dict) -> str:
        """Execute knowledge_add tool."""
        if not self._db:
            return "Knowledge base not initialized"

        content = args.get("content", "")
        if not content:
            return "Error: content is required"

        title = args.get("title")
        url = args.get("url")
        source = args.get("source", "agent")
        tags = args.get("tags", [])

        # Generate embedding if available
        embedding = None
        if self._embeddings and self._embeddings.is_available():
            # Combine title and content for embedding
            embed_text = f"{title or ''} {content}".strip()
            embedding = self._embeddings.embed(embed_text)

        entry_id = self._db.insert(
            content=content,
            title=title,
            url=url,
            source=source,
            tags=tags,
            embedding=embedding,
        )

        embed_status = "with embedding" if embedding else "without embedding"
        return f"Added entry #{entry_id} ({embed_status})"

    def _tool_stats(self) -> str:
        """Execute knowledge_stats tool."""
        if not self._db:
            return "Knowledge base not initialized"

        total = self._db.count()
        with_embeddings = self._db.count_with_embeddings()

        stats = [
            "Knowledge Base Statistics:",
            f"  Total entries: {total}",
            f"  With embeddings: {with_embeddings}",
            f"  Without embeddings: {total - with_embeddings}",
            f"  Database: {self._db_path}",
            f"  Embeddings enabled: {self._embedding_enabled}",
        ]

        if self._embeddings:
            stats.append(f"  Embedding model: {self._embedding_model}")
            stats.append(f"  Ollama available: {self._embeddings.is_available()}")

        return "\n".join(stats)

    # --- Public API for other plugins ---

    def ingest(
        self,
        content: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        source: str = "plugin",
        tags: Optional[list[str]] = None,
    ) -> Optional[int]:
        """Ingest a new entry (for use by other plugins).

        Args:
            content: Main content text
            title: Optional title
            url: Optional source URL
            source: Source identifier
            tags: Optional tags

        Returns:
            Entry ID or None if failed
        """
        if not self._db:
            return None

        # Generate embedding if available
        embedding = None
        if self._embeddings and self._embeddings.is_available():
            embed_text = f"{title or ''} {content}".strip()
            embedding = self._embeddings.embed(embed_text)

        return self._db.insert(
            content=content,
            title=title,
            url=url,
            source=source,
            tags=tags or [],
            embedding=embedding,
        )

    def search(self, query: str, mode: str = "hybrid", limit: int = 10) -> list[dict]:
        """Search the knowledge base (for use by other plugins).

        Args:
            query: Search query
            mode: "fts", "vector", or "hybrid"
            limit: Maximum results

        Returns:
            List of result dicts with entry data and scores
        """
        if not self._search:
            return []

        results = self._search.search(query, mode=mode, limit=limit)
        return [
            {
                "id": r.entry.id,
                "title": r.entry.title,
                "content": r.entry.content,
                "url": r.entry.url,
                "source": r.entry.source,
                "tags": r.entry.tags,
                "score": r.score,
                "match_type": r.match_type,
            }
            for r in results
        ]


def create_plugin() -> KnowledgePlugin:
    """Factory function to create the plugin."""
    return KnowledgePlugin()
