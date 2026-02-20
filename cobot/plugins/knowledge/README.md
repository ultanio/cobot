# Knowledge Plugin

Local vector search and long-term memory for Cobot.

## Overview

The knowledge plugin provides semantic search over a local knowledge base using:
- **SQLite + FTS5** for keyword search
- **Ollama embeddings** for vector/semantic search (optional)

All data stays local — zero cloud dependencies, privacy-preserving.

## Features

- **Hybrid search**: Combines keyword (FTS5) and vector similarity
- **Local embeddings**: Via Ollama with nomic-embed-text (~300MB RAM)
- **Tool integration**: Agents can search and add entries via tools
- **Plugin API**: Other plugins can ingest and query the knowledge base
- **Extension points**: Hooks for enriching ingestion and filtering results

## Configuration

```yaml
# cobot.yml
knowledge:
  db_path: ~/.cobot/knowledge.db
  embedding_enabled: true
  embedding_model: nomic-embed-text
  ollama_url: http://localhost:11434
```

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `db_path` | `~/.cobot/knowledge.db` | SQLite database location |
| `embedding_enabled` | `true` | Enable vector embeddings |
| `embedding_model` | `nomic-embed-text` | Ollama model for embeddings |
| `ollama_url` | `http://localhost:11434` | Ollama API endpoint |

### Running Without Embeddings

For resource-constrained environments, disable embeddings:

```yaml
knowledge:
  embedding_enabled: false
```

This provides keyword search only (FTS5) — still useful, just no semantic matching.

## Tools

The plugin provides three tools for agent use:

### knowledge_search

Search the knowledge base.

```json
{
  "query": "how to configure nostr relay",
  "mode": "hybrid",
  "limit": 5
}
```

Modes:
- `fts` — Keyword search (fast, exact matches)
- `semantic` — Vector similarity (understands meaning)
- `hybrid` — Combined (best of both)

### knowledge_add

Add an entry to the knowledge base.

```json
{
  "content": "The capital of France is Paris.",
  "title": "Geography fact",
  "source": "conversation",
  "tags": ["geography", "europe"]
}
```

### knowledge_stats

Get statistics about the knowledge base.

## Plugin API

Other plugins can use the knowledge base:

```python
# Get the knowledge plugin
knowledge = registry.get("knowledge")

# Add an entry
entry_id = knowledge.ingest(
    content="Important fact here",
    title="My Entry",
    source="my-plugin",
    tags=["tag1", "tag2"],
)

# Search
results = knowledge.search("query", mode="hybrid", limit=10)
for r in results:
    print(f"{r['title']}: {r['content'][:100]}")
```

## Extension Points

### knowledge.before_ingest

Called before an entry is stored. Plugins can enrich or filter.

```python
async def on_knowledge_before_ingest(self, ctx: dict) -> dict:
    entry = ctx["entry"]
    # Add automatic tags
    if "bitcoin" in entry["content"].lower():
        entry.setdefault("tags", []).append("crypto")
    return ctx
```

### knowledge.after_search

Called after search results are computed. Plugins can re-rank or filter.

```python
async def on_knowledge_after_search(self, ctx: dict) -> dict:
    results = ctx["results"]
    # Filter out old entries
    ctx["results"] = [r for r in results if r.entry.created_at > threshold]
    return ctx
```

## Setup Ollama

For semantic search, install Ollama and pull the embedding model:

```bash
# Install Ollama (see https://ollama.ai)
curl -fsSL https://ollama.ai/install.sh | sh

# Pull the embedding model
ollama pull nomic-embed-text
```

The model uses ~300MB RAM when loaded.

## Database Schema

```sql
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    title TEXT,
    content TEXT NOT NULL,
    url TEXT,
    source TEXT DEFAULT 'manual',
    tags TEXT DEFAULT '[]',       -- JSON array
    embedding TEXT,               -- JSON array of floats
    created_at INTEGER,
    updated_at INTEGER
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE entries_fts USING fts5(
    title, content, tags,
    content='entries', content_rowid='id'
);
```

## Philosophy

This plugin follows Cobot's self-sovereign design:
- **Local first**: All data in SQLite, all compute via Ollama
- **Optional dependencies**: Works without embeddings
- **Composable**: Extension points for other plugins
- **Minimal scope**: Storage + search + tools — nothing more
