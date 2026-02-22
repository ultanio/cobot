"""Tests for knowledge plugin."""

import tempfile
from pathlib import Path

import pytest

from cobot.plugins.knowledge.db import KnowledgeDB
from cobot.plugins.knowledge.search import KnowledgeSearch, cosine_similarity


class TestKnowledgeDB:
    """Tests for the database layer."""

    def test_insert_and_get(self):
        """Test inserting and retrieving an entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            entry_id = db.insert(
                content="Test content here",
                title="Test Title",
                source="test",
                tags=["tag1", "tag2"],
            )

            entry = db.get(entry_id)
            assert entry is not None
            assert entry.title == "Test Title"
            assert entry.content == "Test content here"
            assert entry.source == "test"
            assert entry.tags == ["tag1", "tag2"]
            assert entry.embedding is None

            db.close()

    def test_fts_search(self):
        """Test full-text search."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            # Insert test entries
            db.insert(content="Python is a programming language", source="test")
            db.insert(content="JavaScript runs in browsers", source="test")
            db.insert(content="Python can be used for web development", source="test")

            # Search for Python
            results = db.search_fts("Python", limit=10)
            assert len(results) == 2
            assert all("Python" in r.content for r in results)

            # Search for JavaScript
            results = db.search_fts("JavaScript", limit=10)
            assert len(results) == 1
            assert "JavaScript" in results[0].content

            db.close()

    def test_delete(self):
        """Test deleting an entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            entry_id = db.insert(content="To be deleted", source="test")
            assert db.get(entry_id) is not None

            deleted = db.delete(entry_id)
            assert deleted is True
            assert db.get(entry_id) is None

            db.close()

    def test_count(self):
        """Test entry counting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            assert db.count() == 0

            db.insert(content="Entry 1", source="test")
            db.insert(content="Entry 2", source="test")

            assert db.count() == 2

            db.close()

    def test_update_embedding(self):
        """Test updating embeddings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            entry_id = db.insert(content="Test content", source="test")
            assert db.count_with_embeddings() == 0

            db.update_embedding(entry_id, [0.1, 0.2, 0.3])

            entry = db.get(entry_id)
            assert entry is not None
            assert entry.embedding == [0.1, 0.2, 0.3]
            assert db.count_with_embeddings() == 1

            db.close()


class TestCosineSimilarity:
    """Tests for cosine similarity."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity 1.0."""
        v = [1.0, 2.0, 3.0]
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity 0.0."""
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        """Opposite vectors should have similarity -1.0."""
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_different_lengths(self):
        """Different length vectors should return 0.0."""
        a = [1.0, 2.0]
        b = [1.0, 2.0, 3.0]
        assert cosine_similarity(a, b) == 0.0


class TestKnowledgeSearch:
    """Tests for the search layer."""

    def test_fts_search(self):
        """Test FTS search through the search layer."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            db.insert(content="The quick brown fox", source="test")
            db.insert(content="The lazy dog sleeps", source="test")

            search = KnowledgeSearch(db)
            results = search.search_fts("fox", limit=5)

            assert len(results) == 1
            assert results[0].entry.content == "The quick brown fox"
            assert results[0].match_type == "fts"

            db.close()

    def test_search_modes(self):
        """Test different search modes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db = KnowledgeDB(Path(tmpdir) / "test.db")
            db.open()

            db.insert(content="Test content for searching", source="test")

            search = KnowledgeSearch(db)

            # FTS mode
            results = search.search("content", mode="fts")
            assert len(results) >= 1

            # Vector mode without embeddings should return empty
            results = search.search("content", mode="vector")
            assert len(results) == 0

            # Hybrid falls back to FTS when no embeddings
            results = search.search("content", mode="hybrid")
            assert len(results) >= 1

            db.close()
