"""Search logic for knowledge plugin.

Combines FTS5 keyword search with optional vector similarity search.
"""

import math
from dataclasses import dataclass
from typing import Optional

from .db import KnowledgeDB, KnowledgeEntry
from .embeddings import OllamaEmbeddings


@dataclass
class SearchResult:
    """A search result with relevance score."""

    entry: KnowledgeEntry
    score: float
    match_type: str  # "fts", "vector", or "hybrid"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0

    dot_product = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return dot_product / (norm_a * norm_b)


class KnowledgeSearch:
    """Search engine combining FTS and vector search."""

    def __init__(
        self,
        db: KnowledgeDB,
        embeddings: Optional[OllamaEmbeddings] = None,
    ):
        self.db = db
        self.embeddings = embeddings

    def search_fts(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Full-text search using FTS5."""
        entries = self.db.search_fts(query, limit)
        # FTS5 returns results ordered by BM25 score (lower is better)
        # Normalize to 0-1 range where higher is better
        results = []
        for i, entry in enumerate(entries):
            # Simple rank normalization: first result = 1.0, decreases
            score = 1.0 - (i / max(len(entries), 1))
            results.append(SearchResult(entry=entry, score=score, match_type="fts"))
        return results

    def search_vector(self, query: str, limit: int = 10) -> list[SearchResult]:
        """Vector similarity search using embeddings."""
        if not self.embeddings or not self.embeddings.is_available():
            return []

        # Get query embedding
        query_embedding = self.embeddings.embed(query)
        if not query_embedding:
            return []

        # Get all entries with embeddings and compute similarity
        entries = self.db.get_all_with_embeddings()
        scored = []
        for entry in entries:
            if entry.embedding:
                score = cosine_similarity(query_embedding, entry.embedding)
                scored.append((entry, score))

        # Sort by similarity (descending) and take top N
        scored.sort(key=lambda x: x[1], reverse=True)
        return [
            SearchResult(entry=entry, score=score, match_type="vector")
            for entry, score in scored[:limit]
        ]

    def search_hybrid(
        self,
        query: str,
        limit: int = 10,
        fts_weight: float = 0.5,
        vector_weight: float = 0.5,
    ) -> list[SearchResult]:
        """Hybrid search combining FTS and vector results.

        Args:
            query: Search query
            limit: Maximum results to return
            fts_weight: Weight for FTS scores (0-1)
            vector_weight: Weight for vector scores (0-1)

        Returns:
            Combined and re-ranked results
        """
        # Get results from both methods
        fts_results = self.search_fts(query, limit * 2)
        vector_results = self.search_vector(query, limit * 2)

        # Build score map by entry ID
        scores: dict[int, dict] = {}

        for result in fts_results:
            scores[result.entry.id] = {
                "entry": result.entry,
                "fts_score": result.score,
                "vector_score": 0.0,
            }

        for result in vector_results:
            if result.entry.id in scores:
                scores[result.entry.id]["vector_score"] = result.score
            else:
                scores[result.entry.id] = {
                    "entry": result.entry,
                    "fts_score": 0.0,
                    "vector_score": result.score,
                }

        # Compute combined scores
        combined = []
        for entry_id, data in scores.items():
            combined_score = (
                data["fts_score"] * fts_weight + data["vector_score"] * vector_weight
            )
            combined.append(
                SearchResult(
                    entry=data["entry"],
                    score=combined_score,
                    match_type="hybrid",
                )
            )

        # Sort by combined score and return top N
        combined.sort(key=lambda x: x.score, reverse=True)
        return combined[:limit]

    def search(
        self, query: str, mode: str = "hybrid", limit: int = 10
    ) -> list[SearchResult]:
        """Search with specified mode.

        Args:
            query: Search query
            mode: "fts", "vector", or "hybrid"
            limit: Maximum results

        Returns:
            Search results ordered by relevance
        """
        if mode == "fts":
            return self.search_fts(query, limit)
        elif mode == "vector":
            return self.search_vector(query, limit)
        else:  # hybrid
            return self.search_hybrid(query, limit)
