"""
LocalMind RAG Pipeline — Layer 3c
Embeds documents into ChromaDB and retrieves relevant chunks.

Supports indexing:
  - Memory files (SOUL.md, MEMORY.md, daily logs)
  - Any .txt / .md files from a watched directory
"""

import hashlib
import re
from pathlib import Path
from typing import Any

from loguru import logger


class RAGRetriever:
    """
    Manages the ChromaDB vector store and sentence-transformer embeddings.
    Provides semantic search over indexed documents.
    """

    def __init__(
        self,
        persist_dir: str,
        embedding_model: str = "all-MiniLM-L6-v2",
        top_k: int = 5,
        min_score: float = 0.3,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
    ):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.embedding_model_name = embedding_model
        self.top_k = top_k
        self.min_score = min_score
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self._client = None
        self._collection = None
        self._embedder = None
        self._indexed_hashes: set = set()

    async def initialize(self):
        """Load ChromaDB and embedding model."""
        try:
            import chromadb
            from chromadb.config import Settings

            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name="localmind_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(f"ChromaDB initialized — {self._collection.count()} existing chunks")
        except ImportError:
            logger.warning("ChromaDB not installed. RAG will be disabled.")
            return

        try:
            from sentence_transformers import SentenceTransformer
            self._embedder = SentenceTransformer(self.embedding_model_name)
            logger.info(f"Embedding model '{self.embedding_model_name}' loaded")
        except ImportError:
            logger.warning("sentence-transformers not installed. RAG embeddings disabled.")

    # ── Indexing ──────────────────────────────────────────
    async def index_text(self, text: str, doc_id: str, metadata: dict | None = None) -> int:
        """Split text into chunks and index them. Returns number of new chunks added."""
        if not self._collection or not self._embedder:
            return 0

        chunks = self._chunk_text(text)
        if not chunks:
            return 0

        added = 0
        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_id}__chunk_{i}"
            chunk_hash = hashlib.md5(chunk.encode()).hexdigest()

            # Skip if already indexed
            if chunk_hash in self._indexed_hashes:
                continue

            # Check if this ID already exists in collection
            existing = self._collection.get(ids=[chunk_id])
            if existing["ids"]:
                self._indexed_hashes.add(chunk_hash)
                continue

            # Embed and store
            embedding = self._embedder.encode(chunk).tolist()
            self._collection.add(
                ids=[chunk_id],
                embeddings=[embedding],
                documents=[chunk],
                metadatas=[{
                    **(metadata or {}),
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "hash": chunk_hash,
                }],
            )
            self._indexed_hashes.add(chunk_hash)
            added += 1

        if added:
            logger.debug(f"Indexed {added} new chunks from '{doc_id}'")
        return added

    async def index_file(self, file_path: Path) -> int:
        """Index a single file."""
        if not file_path.exists():
            return 0
        try:
            text = file_path.read_text(encoding="utf-8")
            doc_id = str(file_path.relative_to(file_path.parent.parent))
            return await self.index_text(
                text=text,
                doc_id=doc_id,
                metadata={"source": str(file_path), "filename": file_path.name},
            )
        except Exception as e:
            logger.warning(f"Failed to index {file_path}: {e}")
            return 0

    async def index_memory_files(self, memory_dir: str) -> int:
        """Index all memory files (SOUL.md, MEMORY_*.md, daily logs)."""
        total = 0
        mem_path = Path(memory_dir)
        if not mem_path.exists():
            return 0

        for pattern in ["*.md", "*.txt"]:
            for f in mem_path.glob(pattern):
                total += await self.index_file(f)

        # Also index daily logs
        from config.settings import settings
        log_dir = Path(settings.DAILY_LOGS_DIR)
        if log_dir.exists():
            for f in sorted(log_dir.glob("*.md"))[-30:]:  # last 30 days
                total += await self.index_file(f)

        if total:
            logger.info(f"Indexed {total} new chunks from memory files")
        return total

    # ── Retrieval ─────────────────────────────────────────
    async def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Retrieve top-k relevant chunks for a query."""
        if not self._collection or not self._embedder:
            return []

        count = self._collection.count()
        if count == 0:
            return []

        try:
            query_embedding = self._embedder.encode(query).tolist()
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(self.top_k, count),
                include=["documents", "metadatas", "distances"],
            )

            chunks = []
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
                strict=False,
            ):
                # ChromaDB cosine distance → similarity score
                score = 1 - dist
                if score >= self.min_score:
                    chunks.append({
                        "text": doc,
                        "score": score,
                        "source": meta.get("source", "unknown"),
                        "filename": meta.get("filename", ""),
                    })

            logger.debug(f"RAG retrieved {len(chunks)} chunks for query: {query[:50]}")
            return chunks

        except Exception as e:
            logger.error(f"RAG retrieval failed: {e}")
            return []

    # ── Management ────────────────────────────────────────
    async def add_document(self, content: str, title: str, source: str = "user"):
        """Add an arbitrary document to the knowledge base."""
        doc_id = f"doc_{hashlib.md5(content.encode()).hexdigest()[:8]}"
        return await self.index_text(
            text=content,
            doc_id=doc_id,
            metadata={"source": source, "title": title, "filename": title},
        )

    async def get_stats(self) -> dict:
        """Return stats about the knowledge base."""
        if not self._collection:
            return {"chunks": 0, "status": "disabled"}
        return {
            "chunks": self._collection.count(),
            "model": self.embedding_model_name,
            "persist_dir": str(self.persist_dir),
            "status": "active",
        }

    async def clear(self):
        """Delete all indexed data."""
        if self._client and self._collection:
            self._client.delete_collection("localmind_knowledge")
            self._collection = self._client.get_or_create_collection(
                name="localmind_knowledge",
                metadata={"hnsw:space": "cosine"},
            )
            self._indexed_hashes.clear()
            logger.info("RAG knowledge base cleared")

    # ── Text Chunking ─────────────────────────────────────
    def _chunk_text(self, text: str) -> list[str]:
        """Split text into overlapping chunks, respecting paragraph boundaries."""
        if not text.strip():
            return []

        # Split on paragraphs first
        paragraphs = re.split(r"\n{2,}", text)
        chunks = []
        current_chunk = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current_chunk) + len(para) <= self.chunk_size:
                current_chunk += ("\n\n" if current_chunk else "") + para
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                # Handle paragraphs longer than chunk_size
                if len(para) > self.chunk_size:
                    words = para.split()
                    sub = ""
                    for word in words:
                        if len(sub) + len(word) + 1 <= self.chunk_size:
                            sub += (" " if sub else "") + word
                        else:
                            if sub:
                                chunks.append(sub)
                            # Overlap: keep last N chars
                            overlap = sub[-self.chunk_overlap:] if self.chunk_overlap else ""
                            sub = (overlap + " " if overlap else "") + word
                    if sub:
                        current_chunk = sub
                else:
                    # Overlap from previous chunk
                    overlap = current_chunk[-self.chunk_overlap:] if self.chunk_overlap and current_chunk else ""
                    current_chunk = (overlap + "\n\n" if overlap else "") + para

        if current_chunk:
            chunks.append(current_chunk)

        return [c for c in chunks if c.strip()]
