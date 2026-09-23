# rag/ — RAG Knowledge Base

Semantic search over your documents. Files are chunked, embedded with sentence-transformers, and stored in ChromaDB; a query is embedded and matched by cosine similarity, filtered by a score threshold.

## Files

| File | Responsibility |
|------|----------------|
| `__init__.py` | Marks the package. |
| `retriever.py` | RAGRetriever: initialize() (ChromaDB + embedder), index_text/file/memory_files(), retrieve(), get_stats(), clear(). |

## Flow

```mermaid
flowchart TD
    F["docs .md / .txt"] --> CH["chunk (512 / 64 overlap)"]
    CH --> EM["embed (all-MiniLM-L6-v2)"]
    EM --> DB[("ChromaDB")]
    Q["query"] --> QE["embed query"]
    QE --> SR["cosine search"]
    DB --> SR
    SR --> FT["filter by min score"]
    FT --> RES["top-k chunks"]
```

## Example

```python
rag = RAGRetriever(persist_dir="./data/chroma_db")
await rag.initialize()
await rag.index_memory_files("./data/memory")
hits = await rag.retrieve("what did we decide about pricing?")
```

---
_Part of [LocalMind](../README.md). See [docs/architecture.html](architecture.html) for the full interactive architecture and sequence diagrams._
