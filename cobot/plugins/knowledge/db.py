"""SQLite + FTS5 database wrapper for knowledge storage."""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class KnowledgeEntry:
    """A knowledge base entry."""

    id: int
    title: str
    content: str
    url: Optional[str]
    source: str
    tags: list[str]
    embedding: Optional[list[float]]
    created_at: int
    updated_at: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "KnowledgeEntry":
        """Create entry from database row."""
        tags = json.loads(row["tags"]) if row["tags"] else []
        embedding = json.loads(row["embedding"]) if row["embedding"] else None
        return cls(
            id=row["id"],
            title=row["title"] or "",
            content=row["content"],
            url=row["url"],
            source=row["source"],
            tags=tags,
            embedding=embedding,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class KnowledgeDB:
    """SQLite + FTS5 database for knowledge entries."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None

    def open(self) -> None:
        """Open database connection and ensure schema exists."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_schema()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def _create_schema(self) -> None:
        """Create tables if they don't exist."""
        assert self.conn is not None
        cursor = self.conn.cursor()

        # Main entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT,
                content TEXT NOT NULL,
                url TEXT,
                source TEXT NOT NULL DEFAULT 'manual',
                tags TEXT DEFAULT '[]',
                embedding TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

        # FTS5 virtual table for full-text search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                title,
                content,
                tags,
                content='entries',
                content_rowid='id'
            )
        """)

        # Triggers to keep FTS in sync
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, title, content, tags)
                VALUES (new.id, new.title, new.content, new.tags);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, content, tags)
                VALUES ('delete', old.id, old.title, old.content, old.tags);
            END
        """)

        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, content, tags)
                VALUES ('delete', old.id, old.title, old.content, old.tags);
                INSERT INTO entries_fts(rowid, title, content, tags)
                VALUES (new.id, new.title, new.content, new.tags);
            END
        """)

        # Indexes for common queries
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_source ON entries(source)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at)"
        )

        self.conn.commit()

    def insert(
        self,
        content: str,
        title: Optional[str] = None,
        url: Optional[str] = None,
        source: str = "manual",
        tags: Optional[list[str]] = None,
        embedding: Optional[list[float]] = None,
    ) -> int:
        """Insert a new entry. Returns the entry ID."""
        assert self.conn is not None
        now = int(time.time())
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO entries (title, content, url, source, tags, embedding, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                content,
                url,
                source,
                json.dumps(tags or []),
                json.dumps(embedding) if embedding else None,
                now,
                now,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def update_embedding(self, entry_id: int, embedding: list[float]) -> None:
        """Update the embedding for an entry."""
        assert self.conn is not None
        now = int(time.time())
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE entries SET embedding = ?, updated_at = ? WHERE id = ?",
            (json.dumps(embedding), now, entry_id),
        )
        self.conn.commit()

    def get(self, entry_id: int) -> Optional[KnowledgeEntry]:
        """Get an entry by ID."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM entries WHERE id = ?", (entry_id,))
        row = cursor.fetchone()
        return KnowledgeEntry.from_row(row) if row else None

    def delete(self, entry_id: int) -> bool:
        """Delete an entry. Returns True if deleted."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def search_fts(self, query: str, limit: int = 10) -> list[KnowledgeEntry]:
        """Full-text search using FTS5."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        # Use MATCH for FTS5 search with BM25 ranking
        cursor.execute(
            """
            SELECT entries.*, bm25(entries_fts) as rank
            FROM entries
            JOIN entries_fts ON entries.id = entries_fts.rowid
            WHERE entries_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        )
        return [KnowledgeEntry.from_row(row) for row in cursor.fetchall()]

    def get_entries_without_embedding(self, limit: int = 100) -> list[KnowledgeEntry]:
        """Get entries that need embeddings."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM entries WHERE embedding IS NULL ORDER BY created_at LIMIT ?",
            (limit,),
        )
        return [KnowledgeEntry.from_row(row) for row in cursor.fetchall()]

    def get_all_with_embeddings(self) -> list[KnowledgeEntry]:
        """Get all entries that have embeddings (for vector search)."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM entries WHERE embedding IS NOT NULL")
        return [KnowledgeEntry.from_row(row) for row in cursor.fetchall()]

    def count(self) -> int:
        """Get total entry count."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM entries")
        return cursor.fetchone()[0]

    def count_with_embeddings(self) -> int:
        """Get count of entries with embeddings."""
        assert self.conn is not None
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM entries WHERE embedding IS NOT NULL")
        return cursor.fetchone()[0]
