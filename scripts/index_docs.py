"""
LocalMind RAG Indexer
Standalone script to index documents into ChromaDB.
Usage: python scripts/index_docs.py [--dir <path>] [--file <path>] [--clear]
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from config.settings import settings
from rag.retriever import RAGRetriever


async def main():
    parser = argparse.ArgumentParser(description="LocalMind RAG Document Indexer")
    parser.add_argument("--dir", help="Directory to index (all .md/.txt files)")
    parser.add_argument("--file", help="Single file to index")
    parser.add_argument("--clear", action="store_true", help="Clear all indexed data first")
    parser.add_argument("--stats", action="store_true", help="Show indexing stats")
    args = parser.parse_args()

    logger.info("🔍 LocalMind RAG Indexer")
    logger.info("━" * 40)

    rag = RAGRetriever(
        persist_dir=settings.CHROMA_PERSIST_DIR,
        embedding_model=settings.EMBEDDING_MODEL,
        top_k=settings.RAG_TOP_K,
        min_score=settings.RAG_MIN_SCORE,
    )
    await rag.initialize()

    if args.clear:
        logger.info("Clearing all indexed data...")
        await rag.clear()
        logger.info("✅ Cleared")

    if args.stats:
        stats = await rag.get_stats()
        print("\n📊 RAG Stats:")
        for k, v in stats.items():
            print(f"  {k}: {v}")
        return

    total = 0

    if args.file:
        p = Path(args.file)
        count = await rag.index_file(p)
        logger.info(f"Indexed {count} chunks from {p.name}")
        total += count

    elif args.dir:
        p = Path(args.dir)
        if not p.exists():
            logger.error(f"Directory not found: {args.dir}")
            return
        for f in p.rglob("*.md"):
            count = await rag.index_file(f)
            if count:
                logger.info(f"  {f.name}: {count} chunks")
            total += count
        for f in p.rglob("*.txt"):
            count = await rag.index_file(f)
            if count:
                logger.info(f"  {f.name}: {count} chunks")
            total += count
    else:
        # Default: index memory files
        logger.info(f"Indexing memory files from {settings.MEMORY_DIR}...")
        total = await rag.index_memory_files(settings.MEMORY_DIR)

    logger.info(f"✅ Total new chunks indexed: {total}")
    stats = await rag.get_stats()
    logger.info(f"📊 Total chunks in DB: {stats['chunks']}")


if __name__ == "__main__":
    asyncio.run(main())
